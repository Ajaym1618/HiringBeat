# InterBeat Realtime / Socket.IO / Gateway Audit

> **Date:** Inspection-only. No files were modified.
> **Scope:** `interview-webapp-backend`, `device-monitor-backend`, `gateway`

---

## EXECUTIVE SUMMARY

The two backend services are correctly implemented using `python-socketio 5.11.2` in ASGI mode,
combined with FastAPI via `socketio.ASGIApp`. The Gateway has **a critical gap**: it only proxies
Socket.IO WebSocket upgrades — it has **no HTTP route for `/socket.io/*`**. Engine.IO polling
(`?EIO=4&transport=polling`) therefore **fails at the Gateway**, breaking the Socket.IO
connection handshake entirely for any client that does not start directly on WebSocket. Additionally,
device-monitor-backend's `BRIDGE_URL` setting exists in config but the service **never calls it**;
the bridge HTTP call to interview-webapp-backend must originate from the candidate agent, not from
the device-monitor service.

**Verdict: NOT READY FOR REALTIME GATEWAY TESTING** — blocking issues enumerated in Section 10.

---

## 1. LIBRARY AND INITIALISATION

### Interview-webapp-backend

- **Library:** `python-socketio==5.11.2` (file: `interview-webapp-backend/requirements.txt`)
- **Initialisation** (`interview-webapp-backend/app/socket_events.py` line 4):
  ```python
  sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
  ```
- **Combined with FastAPI** (`interview-webapp-backend/app/main.py` last line):
  ```python
  socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
  ```
  `socketio.ASGIApp` wraps the FastAPI `app` as `other_asgi_app`. Uvicorn must be started
  pointing at `socket_app`, **not** `app`, for Socket.IO to function. If started on `app`
  the Socket.IO ASGI path (`/socket.io/`) will never be reached.
- **Engine.IO** is bundled with python-socketio (no separate `python-engineio` pin in
  requirements.txt — it is a transitive dependency).

### Device-monitor-backend

- **Library:** `python-socketio==5.11.2` (file: `device-monitor-backend/requirements.txt`)
- **Initialisation** (`device-monitor-backend/app/socket_events.py` line 3):
  ```python
  sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
  ```
- **Combined with FastAPI** (`device-monitor-backend/app/main.py` last line):
  ```python
  socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
  ```
  Identical pattern to interview-webapp-backend. Same uvicorn startup requirement applies.

### Gateway

- **Library:** No `python-socketio`. Uses `websockets==12.0` and `httpx==0.27.0`.
- Socket.IO proxying is done at the raw WebSocket frame level.

---

## 2. INTERVIEW-WEBAPP-BACKEND TABLE

| Item | Current implementation |
|------|------------------------|
| **Library** | `python-socketio==5.11.2` (AsyncServer + ASGIApp) |
| **Server type** | `socketio.AsyncServer(async_mode="asgi")` |
| **Socket.IO path** | Default: `/socket.io/` (python-socketio default; not overridden anywhere) |
| **Namespace** | Default namespace `/` only (no custom namespaces defined) |
| **Transport** | Both `polling` and `websocket` supported by Engine.IO (default) |
| **CORS (Socket.IO)** | `cors_allowed_origins="*"` — all origins permitted |
| **CORS (FastAPI)** | `allow_origins` from `settings.CORS_ORIGINS` (env var, default `"*"`), `allow_credentials=True`, all methods and headers |
| **Events received (@sio.event)** | `connect`, `disconnect`, `join_room`, `leave_room`, `candidate_ready`, `phone_ready`, `recruiter_present`, `webrtc_offer`, `webrtc_answer`, `webrtc_ice`, `chat_message`, `interview_started`, `interview_ended` |
| **Events emitted (sio.emit)** | `room_joined` (to=sid), `candidate_ready` (room), `phone_ready` (room), `recruiter_present` (room), `webrtc_offer` (room), `webrtc_answer` (room), `webrtc_ice` (room), `chat_message` (room), `interview_started` (room, also from HTTP route), `interview_ended` (room, also from HTTP route), `interview_resumed` (room, from device route), `interview_paused` (room, from device route), `device_usb_alert` (room, from device route), `detection_alert` (room, from monitoring route) |
| **Rooms** | Room name = `interview_code` (8-char hex). Clients join via `join_room` event. Registry `_sid_registry: dict[str, str]` maps sid → interview_code. |
| **Server startup** | Must run: `uvicorn app.main:socket_app --port 5000` (NOT `app:app`) |
| **Port** | 5000 (from `settings.PORT = 5000`) |

### Full event source map (interview-webapp-backend)

| Event emitted | Trigger source | File |
|--------------|---------------|------|
| `room_joined` | `join_room` socket event | `socket_events.py:27` |
| `candidate_ready` | `candidate_ready` socket event | `socket_events.py:42` |
| `phone_ready` | `phone_ready` socket event | `socket_events.py:49` |
| `recruiter_present` | `recruiter_present` socket event | `socket_events.py:56` |
| `webrtc_offer` | `webrtc_offer` socket event | `socket_events.py:63` |
| `webrtc_answer` | `webrtc_answer` socket event | `socket_events.py:70` |
| `webrtc_ice` | `webrtc_ice` socket event | `socket_events.py:77` |
| `chat_message` | `chat_message` socket event | `socket_events.py:84` |
| `interview_started` | `interview_started` socket event OR HTTP `POST /api/interviews/{id}/start` | `socket_events.py:91`, `routes/interviews.py:95` |
| `interview_ended` | `interview_ended` socket event OR HTTP `POST /api/interviews/{id}/end` | `socket_events.py:98`, `routes/interviews.py:110` |
| `interview_resumed` | HTTP `POST /api/device/approve-resume` | `routes/device.py:130` |
| `interview_paused` | HTTP `POST /api/device/event` (event=`paused`) | `routes/device.py:170` |
| `device_usb_alert` | HTTP `POST /api/device/event` (event=`usb_alert`) | `routes/device.py:166` |
| `detection_alert` | HTTP `POST /api/monitoring/alert` | `routes/monitoring.py:45` |

---

## 3. DEVICE-MONITOR-BACKEND TABLE

| Item | Current implementation |
|------|------------------------|
| **Library** | `python-socketio==5.11.2` (AsyncServer + ASGIApp) |
| **Server type** | `socketio.AsyncServer(async_mode="asgi")` |
| **Socket.IO path** | Default: `/socket.io/` |
| **Namespace** | Default namespace `/` only |
| **Transport** | Both `polling` and `websocket` (Engine.IO default) |
| **CORS (Socket.IO)** | `cors_allowed_origins="*"` |
| **CORS (FastAPI)** | `allow_origins=["*"]`, `allow_credentials=True`, all methods and headers (hardcoded, not env-driven) |
| **Events received (@sio.event)** | `connect`, `disconnect` only |
| **Events emitted (sio.emit)** | `candidate_update` (no room — broadcast to all), `usb_alert` (no room — broadcast to all) |
| **Rooms** | **None.** No `sio.enter_room` or room-scoped emit exists anywhere in this service. All Socket.IO emits go to all connected clients. |
| **Server startup** | Must run: `uvicorn app.main:socket_app --port 8081` |
| **Port** | 8081 (from `settings.PORT_DEVICE = 8081`) |

### Device-monitor event detail

| Event emitted | Trigger | Local or bridge? | Payload |
|--------------|---------|-----------------|---------|
| `candidate_update` | `POST /api/report` type=`connect` | Local (candidate agent HTTP POST) | `{session_id, status: "online"}` |
| `candidate_update` | `POST /api/report` type=`full` | Local | `{session_id, device, status}` |
| `candidate_update` | `POST /api/report` type=`quick_update` | Local | `{session_id, running_apps}` |
| `usb_alert` | `POST /api/report` type=`usb_event` | Local | `{session_id, usb_event}` |

**No bridge-originated events exist in device-monitor-backend.** `BRIDGE_URL` is defined in
`device-monitor-backend/app/config.py` but never used — no `httpx` import or call to `BRIDGE_URL`
exists in any `device-monitor-backend/app/**/*.py` file. The bridge direction is:
**interview-webapp-backend receives** via `POST /api/device/event` with `X-Bridge-Key` header,
and **device-monitor-backend does not call it**. The candidate agent is the intended caller.

---

## 4. GATEWAY ANALYSIS

### Route inventory (`gateway/app/main.py`)

| Gateway path | Method | Backend target | Notes |
|-------------|--------|---------------|-------|
| `/health` | GET | — (local) | Liveness probe |
| `/api/{path}` | HTTP all | `INTERVIEW_API_URL/api/{path}` | Full HTTP proxy via httpx |
| `/device/api/{path}` | HTTP all | `DEVICE_MONITOR_API_URL/api/{path}` | Full HTTP proxy via httpx |
| `/socket.io/{path}` | **WebSocket only** | `INTERVIEW_API_URL/socket.io/{path}?{qs}` | Raw WS frame proxy via `websockets` lib |
| `/device/socket.io/{path}` | **WebSocket only** | `DEVICE_MONITOR_API_URL/socket.io/{path}?{qs}` | Raw WS frame proxy via `websockets` lib |

### Critical gap: polling transport not routed

The Socket.IO routes (`@app.websocket(...)`) are FastAPI **WebSocket** decorators. FastAPI only
invokes these handlers for HTTP Upgrade: websocket requests. A plain HTTP GET such as:

```
GET /socket.io/?EIO=4&transport=polling
```

does **not** match a WebSocket route — FastAPI returns 404 or passes the request unhandled.
The `/api/{path}` HTTP proxy route covers `interview-webapp-backend/api/*`, not `/socket.io/*`.

There is **no HTTP proxy route for `/socket.io/*`**.

### Engine.IO handshake failure path

Engine.IO performs an HTTP polling handshake first:

```
Client
  |
  | GET /socket.io/?EIO=4&transport=polling
  v
Gateway :8080
  |
  No matching route → 404 Not Found
  |
  Connection FAILS — Socket.IO client never completes handshake
```

Only if a client forces `transports: ["websocket"]` (skipping polling) would the WebSocket path
work. The default Engine.IO client always starts with polling.

### What the WebSocket proxy does correctly

- Accepts the WebSocket upgrade
- Connects to backend with `websockets.connect()`
- Passes forwarded headers (hop-by-hop headers stripped)
- Forwards query string (EIO, transport, sid parameters preserved)
- Bidirectional frame relay: `client_to_backend` and `backend_to_client` coroutines run concurrently
- Handles `WebSocketDisconnect` and connection close codes

### What the WebSocket proxy does NOT handle correctly

1. **`receive_bytes()` only** — `client_to_backend` calls `client_ws.receive_bytes()` exclusively.
   Socket.IO sends **text frames** for most packets (e.g., `"42["event","data"]"`). Text frames
   from client will raise an exception and silently swallow it, breaking client→server messages.
2. **Silent exception swallowing** — both relay coroutines catch `Exception` with `pass`, hiding
   all errors.
3. **No polling fallback** — as noted above.

---

## 5. RAW WEBSOCKET SEARCH

Search across all `**/*.py` files for `@app.websocket`, `websocket.accept()`, `websocket.receive()`,
`websocket.send()`:

**Only occurrences found are in `gateway/app/main.py` lines 303 and 315** — these are the gateway's
own Socket.IO proxy decorators, not backend endpoints.

> **No raw WebSocket endpoint was found in `interview-webapp-backend` or `device-monitor-backend`;
> realtime communication in both services is implemented through Socket.IO/Engine.IO.**

---

## 6. BRIDGE FLOW TRACE

### Documented architecture vs actual code

#### Step 1 — Recruiter creates interview and generates token

```
Recruiter → POST /api/interviews/          (via Gateway → interview-webapp-backend:5000)
interview-webapp-backend creates Interview document, returns interview_code
Recruiter → POST /api/device/generate-token  (via Gateway → interview-webapp-backend:5000)
interview-webapp-backend stores resume_token on DeviceLink, returns it
```

- HTTP, source: Recruiter browser
- Auth: JWT Bearer (required by `get_current_user` + `require_recruiter`)
- File: `routes/device.py:generate_resume_token`

#### Step 2 — Candidate agent connects to device-monitor

```
Candidate Agent → POST /api/report  (direct to device-monitor-backend:8081, or via Gateway /device/api/report)
body: { type: "connect", candidate_name, hostname, device }
device-monitor-backend creates CandidateSession, emits candidate_update via Socket.IO
returns: { session_id }
```

- HTTP, source: Candidate agent (desktop app)
- Auth: **None** — `POST /api/report` has no authentication
- File: `device-monitor-backend/app/routes/report.py:handle_report`

#### Step 3 — Device-monitor emits to dashboard clients

```
device-monitor-backend → sio.emit("candidate_update", {...})   (no room — broadcast)
Dashboard clients connected to /device/socket.io/ receive it
```

- Socket.IO, local emit
- No interview_code binding — all connected dashboard clients see all candidates

#### Step 4 — USB event from candidate agent

```
Candidate Agent → POST /api/report  (device-monitor-backend)
body: { type: "usb_event", session_id, usb_event: {...} }
device-monitor-backend:
  - persists usb_event to CandidateSession
  - sio.emit("usb_alert", {session_id, usb_event})   ← to all clients
```

- File: `device-monitor-backend/app/routes/report.py` line 79

#### Step 5 — Bridge call: device-monitor → interview-webapp-backend

**⚠ MISSING IN CODE.** The documented bridge step where device-monitor-backend calls
`POST /api/device/event` on interview-webapp-backend **is not implemented** in
device-monitor-backend. `BRIDGE_URL` is configured but never called. No `httpx` usage
exists in any `device-monitor-backend/app/**/*.py` file.

The `POST /api/device/event` endpoint exists in interview-webapp-backend (`routes/device.py:152`)
and is protected by `X-Bridge-Key`. It would need to be called **by the candidate agent or an
external process**, not by device-monitor-backend as currently written.

#### Step 6 — Interview-webapp-backend bridge receives and emits to recruiter

If `POST /api/device/event` is called (by whoever calls it), the flow is:

```
Caller → POST /api/device/event
  headers: X-Bridge-Key: <DEVICE_BRIDGE_KEY>
  body: { interview_code, event: "usb_alert", data: {...} }
interview-webapp-backend validates key (hmac.compare_digest)
  → sio.emit("device_usb_alert", data, room=interview_code)
Recruiter frontend (connected to /socket.io/, in room interview_code) receives device_usb_alert
```

```
event: "paused"  → sio.emit("interview_paused", ..., room=interview_code)
event: "resume_requested" → sets link.resume_requested flag (no Socket.IO emit)
event: "status_update"    → sets link.status (no Socket.IO emit)
```

- File: `interview-webapp-backend/app/routes/device.py:152-175`

#### Revised actual flow

```
Candidate Agent
  |
  | POST /api/report (usb_event)
  v
device-monitor-backend :8081
  |
  | sio.emit("usb_alert") → all dashboard Socket.IO clients (no interview scoping)
  |
  | [BRIDGE CALL MISSING — device-monitor never calls interview-webapp-backend]
  |
  X (no call made)

---

Recruiter must call POST /api/device/approve-resume via gateway for resume flow
  |
  v
interview-webapp-backend:5000
  |
  | sio.emit("interview_resumed", room=interview_code)
  v
Recruiter frontend receives event
```

---

## 7. SECURITY AUDIT

| Check | Rating | Evidence / Detail |
|-------|--------|-------------------|
| **Socket.IO CORS — interview-webapp-backend** | ⚠ WARNING | `cors_allowed_origins="*"` — all origins can connect. Acceptable in development; needs restriction for production. |
| **Socket.IO CORS — device-monitor-backend** | ⚠ WARNING | `cors_allowed_origins="*"` — identical issue. |
| **FastAPI CORS — interview-webapp-backend** | ⚠ WARNING | `settings.CORS_ORIGINS` defaults to `"*"`. Origins controlled via env var — correct pattern but insecure default. |
| **FastAPI CORS — device-monitor-backend** | ⚠ WARNING | Hardcoded `allow_origins=["*"]` — not env-driven. Less flexible than interview service. |
| **JWT for Socket.IO connections** | ⚠ WARNING | `connect` handler accepts `auth` parameter but performs no validation (`print(f"[socket] connect: {sid}")` then returns). Any unauthenticated client can connect. |
| **JWT for Socket.IO events** | 🔴 SECURITY ISSUE | No event handler in either service checks JWT or any credential. Any connected client can emit any event including `join_room`, `interview_started`, `interview_ended`. |
| **Room isolation** | ⚠ WARNING | Rooms are keyed by `interview_code` (8-char hex = ~4 billion combinations). No proof-of-identity required to join any room — any client that knows the code can join and receive all recruiter and candidate events. |
| **Company isolation in events** | 🔴 SECURITY ISSUE | No company_id filtering on Socket.IO events. All events are scoped only by `interview_code` (guessable). Cross-company access is possible if code is guessed or leaked. |
| **Bridge key validation** | ✅ PASS | `hmac.compare_digest` used (timing-safe) in `routes/device.py:154`. Key sourced from `settings.DEVICE_BRIDGE_KEY`. |
| **Bridge key default** | ⚠ WARNING | Default is `"change-me"` in both services. If `.env` is not set, the bridge key provides no security. |
| **Dashboard key validation** | ⚠ WARNING | `_require_dashboard_key` in `candidates.py:10` uses plain `!=` comparison (not timing-safe). Vulnerable to timing attack. |
| **POST /api/report (device-monitor)** | 🔴 SECURITY ISSUE | No authentication at all. Any internet-accessible device can POST arbitrary candidate sessions and USB events. |
| **Gateway open proxy prevention** | ✅ PASS | Gateway only routes `/api/{path}` → interview API and `/device/api/{path}` → device API. No wildcard passthrough, no user-controlled URL construction. |
| **Gateway exposes internal ports** | ✅ PASS | Gateway does not expose :5000 or :8081 directly. Both are proxied through :8080. |
| **Sensitive candidate info broadcast** | 🔴 SECURITY ISSUE | device-monitor `sio.emit("candidate_update", ...)` and `sio.emit("usb_alert", ...)` broadcast to **all connected clients with no room or interview scoping**. Any connected Socket.IO client receives every candidate's device telemetry. |
| **Interview event broadcast** | ✅ PASS | interview-webapp-backend emits to rooms — only clients in the correct `interview_code` room receive events. |
| **Gateway auth header forwarding** | ✅ PASS | `_filter_request_headers` strips hop-by-hop headers but forwards `Authorization`, `X-Bridge-Key`, `X-Dashboard-Key` to backends. |

---

## 8. GATEWAY DEPENDENCIES

`gateway/requirements.txt`:
```
fastapi==0.111.0
uvicorn==0.29.0
httpx==0.27.0
pydantic-settings==2.2.1
python-dotenv==1.0.1
websockets==12.0
```

### Analysis

| Dependency | Present | Verdict |
|-----------|---------|---------|
| `fastapi` | ✅ | Required for HTTP routing and WebSocket decorator |
| `uvicorn` | ✅ | ASGI server |
| `httpx` | ✅ | Required for `_proxy_request` HTTP proxy |
| `websockets` | ✅ | Required for `websockets.connect()` in `_proxy_websocket` |
| `pydantic-settings` | ✅ | Required for `Settings` class in `config.py` |
| `python-dotenv` | ✅ | Required for `.env` loading |

**The current dependency set is sufficient for what the gateway currently does.**

However, the current gateway **does not solve the polling transport problem**. The fix would
require routing HTTP GET/POST to `/socket.io/` through the HTTP proxy. That fix requires
**no new dependencies** — the existing `httpx` client can handle it. The missing piece is a
route definition, not a missing library.

### Missing dependency for text frame handling (WebSocket proxy)

The `websockets` library is present. The bug (text frames dropped) is a code issue in
`_proxy_websocket`, not a dependency issue.

---

## 9. DOC vs CODE GAP

### Documented routing target

```
/socket.io/*          → interview-webapp-backend:5000
/device/socket.io/*   → device-monitor-backend:8081
```

### Actual routing in `gateway/app/main.py`

| Client request | Gateway handler | Works? |
|---------------|----------------|--------|
| `GET /socket.io/?EIO=4&transport=polling` | No matching route | ❌ 404 |
| `WebSocket /socket.io/?EIO=4&transport=websocket` | `interview_ws_proxy` | ⚠ Partial (text frames dropped) |
| `GET /socket.io/` (Engine.IO handshake) | No matching HTTP route | ❌ 404 |
| `GET /device/socket.io/?EIO=4&transport=polling` | No matching route | ❌ 404 |
| `WebSocket /device/socket.io/?EIO=4&transport=websocket` | `device_ws_proxy` | ⚠ Partial (text frames dropped) |

The gateway satisfies the WebSocket upgrade leg of the documented routing, but only partially
(text frames bug). It does **not** satisfy the polling leg at all.

---

## 10. VERDICT AND BLOCKING ISSUES

**VERDICT: NOT READY FOR REALTIME GATEWAY TESTING**

### Blocking Issues

#### BLOCKER 1 — No HTTP route for `/socket.io/*` (polling transport broken)

Engine.IO's default transport sequence is: HTTP polling → upgrade to WebSocket. The gateway
has no HTTP route for `/socket.io/` or `/device/socket.io/`. The Engine.IO handshake
(first HTTP request) returns 404. All Socket.IO clients fail to connect unless forced to
`transports: ["websocket"]`, which skips Engine.IO's reliability handshake.

**Fix required:** Add HTTP proxy routes for `/socket.io/{path}` and `/device/socket.io/{path}`
in gateway, routing them to the respective backends. This is the same `_proxy_request` pattern
already used for `/api/{path}`.

#### BLOCKER 2 — WebSocket proxy drops text frames (client→server)

`_proxy_websocket` calls `client_ws.receive_bytes()` (binary only). Socket.IO protocol sends
text frames (e.g., `"42[\"event\",{...}]"`). These calls will raise `WebSocketDisconnect` or
a type mismatch error, which is silently swallowed. Client-to-server Socket.IO messages are
therefore lost.

**Fix required:** Use `client_ws.receive()` (returns dict with `text` or `bytes` key) and
dispatch appropriately to `backend_ws.send(text/bytes)`.

#### BLOCKER 3 — Bridge not implemented in device-monitor-backend

`BRIDGE_URL` is configured but never called. The bridge USB alert flow (device-monitor →
interview-webapp-backend → recruiter Socket.IO) is documented but the HTTP call is missing.
The `POST /api/device/event` endpoint on interview-webapp-backend exists and is correct, but
nothing calls it from device-monitor-backend.

**Fix required:** In `device-monitor-backend/app/routes/report.py` `usb_event` handler,
add an `httpx` call to `{settings.BRIDGE_URL}/api/device/event` with `X-Bridge-Key` header
and bridge payload.

#### BLOCKER 4 — Socket.IO has no authentication

Any anonymous WebSocket client can connect and join any interview room, receive all events
(including WebRTC signaling, chat, device alerts), and emit events as if they were a recruiter
or candidate. The `connect` handler ignores the `auth` parameter entirely.

**Fix required:** Validate a JWT or token in the `connect` handler. Return `False` to reject
unauthenticated connections.

#### SECURITY ISSUE 5 — device-monitor Socket.IO emits are unscoped (broadcast)

`sio.emit("candidate_update", ...)` and `sio.emit("usb_alert", ...)` in device-monitor-backend
go to all connected Socket.IO clients. There is no room-based isolation. Any dashboard client
sees every candidate's data.

**Fix required:** Implement rooms in device-monitor-backend (e.g., keyed by `session_id` or
an interview-scoped token) so emits are directed to the correct observer.

### Non-blocking issues

- Default secrets (`"change-me"`) in both services' configs — deployment risk, not a code bug.
- `_require_dashboard_key` uses non-timing-safe comparison (`!=`) — low risk but should use `hmac.compare_digest`.
- `POST /api/report` has no authentication — appropriate for internal candidate agent use but risky if the endpoint is exposed through the gateway.
- PDF generation in `device-monitor-backend/app/routes/candidates.py` is a stub.

---

## 11. APPENDIX — Complete Realtime Event Reference

### interview-webapp-backend — all Socket.IO events

#### Received from clients

| Event | Handler file | Data expected | Action |
|-------|------------|--------------|--------|
| `connect` | `socket_events.py:12` | `auth` (ignored) | Logs sid |
| `disconnect` | `socket_events.py:17` | — | Removes from `_sid_registry` |
| `join_room` | `socket_events.py:23` | `{interview_code}` | `enter_room`, registry update, emit `room_joined` |
| `leave_room` | `socket_events.py:32` | `{interview_code}` | `leave_room`, registry remove |
| `candidate_ready` | `socket_events.py:40` | any | Broadcast to room |
| `phone_ready` | `socket_events.py:47` | any | Broadcast to room |
| `recruiter_present` | `socket_events.py:54` | any | Broadcast to room |
| `webrtc_offer` | `socket_events.py:61` | SDP offer | Broadcast to room |
| `webrtc_answer` | `socket_events.py:68` | SDP answer | Broadcast to room |
| `webrtc_ice` | `socket_events.py:75` | ICE candidate | Broadcast to room |
| `chat_message` | `socket_events.py:82` | chat data | Broadcast to room |
| `interview_started` | `socket_events.py:89` | any | Broadcast to room (including sender) |
| `interview_ended` | `socket_events.py:96` | any | Broadcast to room (including sender) |

#### Emitted by server

| Event | Destination | Trigger |
|-------|------------|---------|
| `room_joined` | sender only | `join_room` |
| `candidate_ready` | room (skip sender) | `candidate_ready` |
| `phone_ready` | room (skip sender) | `phone_ready` |
| `recruiter_present` | room (skip sender) | `recruiter_present` |
| `webrtc_offer` | room (skip sender) | `webrtc_offer` |
| `webrtc_answer` | room (skip sender) | `webrtc_answer` |
| `webrtc_ice` | room (skip sender) | `webrtc_ice` |
| `chat_message` | room (skip sender) | `chat_message` |
| `interview_started` | room (all) | socket event OR `POST /api/interviews/{id}/start` |
| `interview_ended` | room (all) | socket event OR `POST /api/interviews/{id}/end` |
| `interview_resumed` | room (all) | `POST /api/device/approve-resume` |
| `interview_paused` | room (all) | `POST /api/device/event` event=`paused` |
| `device_usb_alert` | room (all) | `POST /api/device/event` event=`usb_alert` |
| `detection_alert` | room (all) | `POST /api/monitoring/alert` |

### device-monitor-backend — all Socket.IO events

#### Received from clients

| Event | File | Action |
|-------|------|--------|
| `connect` | `socket_events.py:8` | Logs sid |
| `disconnect` | `socket_events.py:13` | Logs sid |

#### Emitted by server

| Event | Trigger endpoint | Broadcast scope | Payload |
|-------|----------------|----------------|---------|
| `candidate_update` | `POST /api/report` type=`connect` | **All clients (no room)** | `{session_id, status: "online"}` |
| `candidate_update` | `POST /api/report` type=`full` | **All clients (no room)** | `{session_id, device, status}` |
| `candidate_update` | `POST /api/report` type=`quick_update` | **All clients (no room)** | `{session_id, running_apps}` |
| `usb_alert` | `POST /api/report` type=`usb_event` | **All clients (no room)** | `{session_id, usb_event}` |

---

*End of audit. No files were modified.*
