# InterBeat Backend — Monorepo

This repository contains the two backend services for the **InterBeat** remote proctoring platform.

| Service | Folder | Port | Database |
|---|---|---|---|
| Interview API | `interbeat-interview-webapp-backend/` | 5000 | `interbeat_interview` |
| Device Monitor API | `interbeat-device-monitor-backend/` | 8081 | `interbeat_monitoring` |

---

## Architecture Overview

```
interbeat-interview-webapp-backend/    ← core backend (auth, interviews, AI, WebRTC)
interbeat-device-monitor-backend/      ← device telemetry backend (USB, Wi-Fi, apps)
.env                                   ← shared environment variables (both services read this)
.env.example                           ← template — copy this to .env
```

Both services share **one `.env` file** at the root. Each service only reads the variables it needs and ignores the rest.

---

## Tech Stack

- **FastAPI** — async web framework
- **MongoDB** — document database (via MongoDB Atlas or local)
- **Motor 3.4.0** — async MongoDB driver
- **Beanie 1.25.0** — async ODM built on Motor + Pydantic
- **PyMongo 4.6.3** — required by Motor (must be this exact version)
- **Pydantic v2** — data validation
- **python-socketio** — Socket.IO for real-time events
- **PyJWT / passlib** — JWT auth + bcrypt password hashing (interview_api only)
- **Uvicorn** — ASGI server

---

## Prerequisites

- Python **3.10 or newer**
- MongoDB running locally OR a MongoDB Atlas URI
- Two separate terminal windows (one per service)

---

## ⚠️ Known Version Requirement

> **pymongo must be pinned to 4.6.3**

Motor 3.4.0 is incompatible with pymongo 4.7+. If you install without pinned versions you will get:
```
ImportError: cannot import name '_QUERY_OPTIONS' from 'pymongo.cursor'
```

Both `requirements.txt` files already pin `pymongo==4.6.3`. As long as you install from `requirements.txt`, this will not be an issue.

---

## Setup

### 1. Clone the repo

```powershell
git clone <repo-url>
cd "InterBeat backend"
```

### 2. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in your values — at minimum set:
- `MONGO_URI` — your MongoDB connection string
- `SECRET_KEY` — any long random string
- `DEVICE_BRIDGE_KEY` — any long random string
- `DASHBOARD_API_KEY` — any long random string

### 3. Set up and run Interview API

```powershell
cd interbeat-interview-webapp-backend

# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# If activation fails due to execution policy, run this first:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 5000
```

Swagger UI → http://localhost:5000/docs

### 4. Set up and run Device Monitor API (new terminal)

```powershell
cd interbeat-device-monitor-backend

# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8081
```

Swagger UI → http://localhost:8081/docs

---

## Environment Variables

All variables live in the root `.env` file.

### Shared (used by both services)

| Variable | Description |
|---|---|
| `SECRET_KEY` | Signs JWT tokens |
| `DEVICE_BRIDGE_KEY` | Shared secret between interview_api and device_monitor_api |
| `DASHBOARD_API_KEY` | Required to read candidate device data |

### Interview API

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME` | `interbeat_interview` | Database name |
| `JWT_EXPIRY_HOURS` | `24` | JWT token expiry in hours |
| `DEVICE_MONITOR_URL` | `http://localhost:8081` | URL of device_monitor_api |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `UPLOAD_FOLDER` | `uploads` | Folder for screenshot uploads |
| `PORT` | `5000` | Server port |

### Device Monitor API

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI_DEVICE` | `mongodb://localhost:27017` | MongoDB connection string |
| `DB_NAME_DEVICE` | `interbeat_monitoring` | Database name |
| `BRIDGE_URL` | `http://localhost:5000` | URL of interview_api |
| `PORT_DEVICE` | `8081` | Server port |

---

## API Documentation

Once both servers are running:

| Service | Swagger UI | ReDoc |
|---|---|---|
| Interview API | http://localhost:5000/docs | http://localhost:5000/redoc |
| Device Monitor API | http://localhost:8081/docs | http://localhost:8081/redoc |

---

## Common Errors & Fixes

### `uvicorn` not recognized
```
uvicorn : The term 'uvicorn' is not recognized...
```
**Fix:** You haven't installed dependencies yet. Run `pip install -r requirements.txt` first.

---

### bcrypt / passlib error
```
(trapped) error reading bcrypt version
AttributeError: module 'bcrypt' has no attribute '__about__'
```
**Fix:** `passlib` is incompatible with `bcrypt 4.x`. The codebase uses `bcrypt` directly — make sure `passlib` is not installed:
```powershell
pip uninstall passlib -y
pip install "bcrypt==4.0.1"
```


```
ImportError: cannot import name '_QUERY_OPTIONS' from 'pymongo.cursor'
```
**Fix:** Your pymongo version is too new. Run:
```powershell
pip install "pymongo==4.6.3" "motor==3.4.0" "beanie==1.25.0"
```

---

### Pydantic ValidationError — Extra inputs not permitted
```
pydantic_core.ValidationError: Extra inputs are not permitted
```
**Fix:** Both services share one `.env` file. Make sure both `config.py` files have `extra = "ignore"` in the `Config` class. This is already set — if you see this error, pull the latest code.

---

### PowerShell execution policy error
```
.\venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled
```
**Fix:** Run this once in PowerShell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Services Overview

### Interview API (`interbeat-interview-webapp-backend`)
Handles everything user-facing:
- Auth — register, login, JWT tokens, roles
- Interviews — create, start, end, logs
- AI Detection — YOLO/MediaPipe frame analysis (stub, to be completed by AI team)
- WebRTC Signaling — offer/answer/ICE for peer-to-peer video
- Device Bridge — communicates with device_monitor_api
- Face Verification — InsightFace identity check (stub, to be completed by AI team)
- Admin — branding, companies, recruiters, installer builds
- Real-time — Socket.IO events for live alerts

### Device Monitor API (`interbeat-device-monitor-backend`)
Handles device telemetry from the candidate's machine:
- Receives reports from candidate-agent (USB, Wi-Fi, apps, heartbeat)
- Serves candidate device snapshots to interview_api
- Pushes live updates via Socket.IO

---

## Project Team

| Area | Handled by |
|---|---|
| Interview API | Backend team |
| Device Monitor API | Backend team |
| Frontend (web-portal, device-dashboard) | Frontend team |
| Electron desktop client | Desktop team |
| Candidate agent (.exe) | Desktop team |
| Gateway | Infrastructure team |
