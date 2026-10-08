# InterBeat Device Monitor API

Device telemetry backend service for the InterBeat remote proctoring platform.

- **Port:** 8081
- **Database:** `interbeat_monitoring` (MongoDB)
- **Swagger UI:** http://localhost:8081/docs

---

## Setup

> Make sure you have set up the root `.env` file first. See the [root README](../README.md).

```powershell
# From inside this folder
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8081
```

---

## What This Service Does

Receives device telemetry reports from the **candidate-agent** (.exe) running on the candidate's machine and serves that data to the recruiter's dashboard via the **interview_api** bridge.

Nobody logs into this service directly — it uses API key authentication instead of JWT.

---

## API Endpoints

### Report — `/api`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/report` | Public | Receive device report from candidate-agent |

#### Report Types (sent in `type` field)
| Type | Trigger | Description |
|---|---|---|
| `full` | Startup + every few minutes | Full device snapshot |
| `quick_update` | USB plug/unplug | Partial update (USB/camera only) |
| `usb_event` | USB device change | USB plug/unplug event |
| `wifi_change` | Wi-Fi SSID change | Wi-Fi network change |
| `heartbeat` | Periodic | Keep-alive ping |
| `app_closed` | Process exit | Agent shutting down |
| `connect` | Startup | Initial connection + token verification |

### Candidates — `/api`
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/candidates` | Dashboard Key | List all candidate sessions |
| GET | `/candidates/{id}` | Dashboard Key | Get single candidate session |
| GET | `/candidates/{id}/pdf` | Dashboard Key | Get candidate device report as HTML |

---

## Authentication

This service uses **two types of API key auth** — no JWT:

| Key | Header | Used by | Protects |
|---|---|---|---|
| `DASHBOARD_API_KEY` | `X-Dashboard-Key` | interview_api | Candidate read endpoints |
| `DEVICE_BRIDGE_KEY` | `X-Bridge-Key` | interview_api bridge | Internal event push |

## Socket.IO Authentication & Authorization

Socket.IO connections require a valid JWT token in the `auth` object:

```js
socket = io("http://localhost:8081", {
  auth: { token: "<recruiter_jwt>" }
})
```

Only `recruiter` and `company_manager` roles may connect and join monitoring sessions. Candidates and unauthenticated clients are rejected.

### Session room authorization

Before joining a `session_{session_id}` room, the service calls the Interview API bridge endpoint (`GET /api/device/session-company/{session_id}`) to resolve the session → DeviceLink → Interview → company ownership chain. A recruiter or company_manager can only join sessions belonging to their own company. `super_admin` may join any session.

### ⚠ Known token-lifetime behavior

The Device Monitor reads `company_id` from the **JWT payload** at connection time. It does **not** perform a live database lookup of the user's current company on every event.

**Implication:** If a recruiter is reassigned to a different company, any already-issued JWT token will still carry the **previous** `company_id` until the token expires (default: 24 hours, configurable via `JWT_EXPIRY_HOURS`).

This is a known, intentional behavior — not a code bug. It is consistent with standard JWT stateless auth design. The window closes when the token expires and the recruiter logs in again.

**Mitigation options (if needed in production):**
- Reduce `JWT_EXPIRY_HOURS` to a shorter window (e.g. 1–2 hours)
- Implement token revocation (e.g. a Redis blocklist) in the Interview API
- Force re-login after company reassignment via the admin panel

---

## Socket.IO Events

Connect to `http://localhost:8081` with Socket.IO.

| Event | Direction | Description |
|---|---|---|
| `candidate_update` | Server → Dashboard | Candidate device data updated |
| `usb_alert` | Server → Dashboard | USB device plugged/unplugged |

---

## Common Errors & Fixes

### pymongo ImportError
```
ImportError: cannot import name '_QUERY_OPTIONS' from 'pymongo.cursor'
```
**Fix:**
```powershell
pip install "pymongo==4.6.3" "motor==3.4.0" "beanie==1.25.0"
```

### Pydantic extra inputs error
```
pydantic_core.ValidationError: Extra inputs are not permitted
```
**Fix:** Make sure `config.py` has `extra = "ignore"` in the `Config` class. Already set in this repo.
