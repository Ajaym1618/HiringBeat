# InterBeat Gateway

A lightweight reverse-proxy gateway built with **FastAPI** and **httpx**.  
Single entry point for the InterBeat platform — routes HTTP requests and WebSocket connections to the two backend services.

---

## Architecture

| Service | Port | Description |
|---|---|---|
| **Gateway** | 8080 | This service — single entry point |
| **Interview API** | 5000 | Core interview/auth/detection/WebRTC backend |
| **Device Monitor API** | 8081 | Device telemetry and monitoring backend |

---

## Route Mapping

| Gateway path | Forwarded to | Notes |
|---|---|---|
| `GET /health` | — | Gateway liveness check |
| `/api/{path}` | `INTERVIEW_API_URL/api/{path}` | All HTTP methods |
| `/device/api/{path}` | `DEVICE_MONITOR_API_URL/api/{path}` | `/device` prefix stripped |
| `/socket.io/{path}` | `INTERVIEW_API_URL/socket.io/{path}` | WebSocket proxy |
| `/device/socket.io/{path}` | `DEVICE_MONITOR_API_URL/socket.io/{path}` | WebSocket proxy |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_PORT` | `8080` | Port the gateway listens on |
| `INTERVIEW_API_URL` | `http://localhost:5000` | Base URL of the Interview API |
| `DEVICE_MONITOR_API_URL` | `http://localhost:8081` | Base URL of the Device Monitor API |
| `PROXY_TIMEOUT` | `30` | Proxy request timeout in seconds |
| `GATEWAY_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins (or `*`) |

All variables are loaded from the shared root `.env` file (`../.env` relative to the `gateway/` directory).

---

## How to Run

```bash
cd gateway
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

# Run on the default port (8080)
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Or use the `GATEWAY_PORT` env var:

```bash
GATEWAY_PORT=9090 uvicorn app.main:app --host 0.0.0.0 --port 9090
```

---

## Socket.IO / WebSocket Limitation

Both backend services use **python-socketio** in ASGI mode (`async_mode="asgi"`), which means Socket.IO is served at the ASGI layer, not as plain HTTP routes.

The gateway handles this in two ways:

1. **HTTP long-polling transport** — Socket.IO's XHR/polling transport sends regular HTTP requests to `/socket.io/...`. These flow through the standard HTTP proxy routes (`/api/...` is not the right path — the `/socket.io/{path}` HTTP routes in the gateway handle polling traffic directly).

2. **WebSocket transport** — The gateway uses the `websockets` library to open a raw WebSocket connection to the backend and bridge frames bidirectionally. This preserves the Socket.IO handshake and event framing without the gateway needing to understand the Socket.IO protocol itself.

**Why not httpx for WebSocket?** `httpx` only supports HTTP/1.1 and HTTP/2 — it does not support WebSocket upgrades. The `websockets` library handles the TCP-level WebSocket protocol, which is required for Socket.IO's WebSocket transport.

---

## Static Files

The gateway does **not** serve any static frontend files. It is a pure API/WebSocket reverse proxy.  
Static file hosting (serving the compiled frontend build) can be added later by mounting a `StaticFiles` directory in `app/main.py`.

---

## How to Run Tests

```bash
cd gateway
pip install -r requirements.txt respx==0.21.1 pytest==8.2.0 pytest-asyncio==0.23.6
pytest tests/ -v
```

Tests use **respx** to mock the upstream HTTP backends and **pytest** for test discovery. No live backend services are needed.

---

## Error Responses

All gateway errors use the same format as the existing backend services:

```json
{
  "success": false,
  "message": "Interview API unavailable",
  "error": { "code": "BAD_GATEWAY" }
}
```

| Scenario | HTTP Status | Error Code |
|---|---|---|
| Backend unreachable / connection refused | 502 | `BAD_GATEWAY` |
| Request timed out | 504 | `GATEWAY_TIMEOUT` |
| Backend 4xx / 5xx | (passed through) | — |

---

## Security Notes

- The gateway only proxies to the two configured backend URLs — there is no open-proxy capability.
- All authentication is handled by the backend services; the gateway forwards auth headers unchanged.
- `Authorization`, `Cookie`, `X-Bridge-Key`, and `X-Dashboard-Key` headers are forwarded but never logged.
- The `Host` header is not blindly forwarded; it is rebuilt from the target URL.
