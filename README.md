# InterBeat Backend — Monorepo

This repository contains the two backend services for the **InterBeat** remote proctoring platform.

| Service | Folder | Port | Database |
|---|---|---|---|
| Interview API | `interview-webapp-backend/` | 5000 | `interbeat_interview` |
| Device Monitor API | `device-monitor-backend/` | 8081 | `interbeat_monitoring` |
| Gateway | `gateway/` | 8080 | — |

---

## Architecture Overview

```
interview-webapp-backend/    ← core backend (auth, interviews, org, subscriptions, AI, WebRTC)
device-monitor-backend/      ← device telemetry backend (USB, Wi-Fi, apps)
gateway/                     ← API gateway / reverse proxy
.env                         ← shared environment variables (both services read this)
.env.example                 ← template — copy this to .env
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
- **aiofiles** — async file I/O for document uploads

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
cd interview-webapp-backend

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
cd device-monitor-backend

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
| `UPLOAD_FOLDER` | `uploads` | Folder for screenshot and org document uploads |
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

## Organization Registration

Organizations self-register via `POST /api/org/register`. After registration the company status is set to `pending_verification` and the manager account is created.

### Required fields

| Field | Description |
|---|---|
| `org_name` | Legal organization name |
| `manager_name` | Full name of the primary manager |
| `manager_email` | Email address (becomes login) |
| `password` | Min 8 chars, 1 uppercase, 1 number |
| `org_type` | e.g. "Private Limited", "NGO", "Government" |
| `registered_address` | Full registered address |
| `official_phone` | Organization contact number |
| `authorized_person_name` | Name of person authorized to act for the org |
| `authorized_person_designation` | Job title of authorized person |
| `authorized_person_email` | Email of authorized person |
| `authorized_person_phone` | Phone of authorized person |

### Optional fields

| Field | Description |
|---|---|
| `registration_number` | CIN or equivalent |
| `pan` | PAN number |
| `gstin` | GST Identification Number |
| `website` | Organization website URL |

---

## Verification Documents

After registration, the manager uploads verification documents via:

```
POST /api/org/{company_id}/documents
Content-Type: multipart/form-data

documents: [file1, file2, ...]
document_types: "certificate_of_incorporation,pan_document"
```

### Allowed document types

| Value | Description |
|---|---|
| `certificate_of_incorporation` | Certificate of Incorporation / Registration Certificate |
| `pan_document` | Organization PAN document |
| `address_proof` | Registered address proof |
| `authorized_person_id` | Authorized person's ID / authorization document |
| `gst_certificate` | GST Certificate (if applicable) |
| `authorization_letter` | Authorization Letter (if applicable) |

### Rules

- Allowed file types: PDF, JPG, PNG (max 10 MB each)
- Files are stored on disk under `UPLOAD_FOLDER/org_docs/{company_id}/`
- Files are **never** stored in MongoDB
- No public URL is returned — documents are only accessible to super_admin via the secure download endpoint

---

## Super Admin Verification

Super admins can review pending organizations and their documents via the `/api/admin/orgs` endpoints.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin/orgs` | List all organizations (supports `?status=` filter) |
| `GET` | `/api/admin/orgs/{company_id}` | Full company detail including org identity fields |
| `GET` | `/api/admin/orgs/pending` | List pending organizations |
| `GET` | `/api/admin/orgs/{company_id}/documents` | List document metadata |
| `GET` | `/api/admin/orgs/{company_id}/documents/{doc_id}/download` | Secure document download |
| `POST` | `/api/admin/orgs/{company_id}/approve` | Approve organization |
| `PATCH` | `/api/admin/orgs/{company_id}/approve` | Approve organization (PATCH alias) |
| `POST` | `/api/admin/orgs/{company_id}/reject` | Reject organization with reason |
| `PATCH` | `/api/admin/orgs/{company_id}/reject` | Reject organization with reason (PATCH alias) |

All `/api/admin/orgs` endpoints require `super_admin` role.

### Organization verification status flow

```
pending_verification  →  active (approved)
                      →  rejected
```

A **pending** organization can log in but cannot create admins, recruiters, or interviews until approved and subscribed.

---

## Subscription Plans

Three built-in plans are seeded at startup:

| Plan | Max Admins | Max Recruiters | Max Interviews |
|---|---|---|---|
| Basic | 1 | 5 | 25 |
| Professional | 3 | 15 | 100 |
| Enterprise | 10 | 50 | 500 |

Super admin assigns a plan to an organization via:

```
PATCH /api/admin/orgs/{company_id}/subscription
{
  "plan_id": "<SubscriptionPlan._id>",
  "expires_at": "2025-12-31T23:59:59Z"  // optional
}
```

View all plans: `GET /api/admin/subscription-plans`

---

## Subscription Enforcement

The backend enforces:

- `verification_status == "approved"` **AND**
- `subscription.status == "active"` **AND**
- subscription not expired

before allowing:

- admin creation (`POST /api/company/team` with role=company_manager)
- recruiter creation (`POST /api/company/team` with role=recruiter)
- interview scheduling (`POST /api/interviews/`)

Limits are checked **separately** — recruiter and admin limits are independent. A 403 is returned when verification is not approved; a 409 is returned when a limit is reached.

---

## Limits

### Basic plan

- Up to **1** company manager (admin)
- Up to **5** recruiters
- Up to **25** interviews total

### Professional plan

- Up to **3** company managers
- Up to **15** recruiters
- Up to **100** interviews total

### Enterprise plan

- Up to **10** company managers
- Up to **50** recruiters
- Up to **500** interviews total

View current usage: `GET /api/admin/orgs/{company_id}/subscription`

---

## Candidate History

Candidates retrieve their own interview history via:

```
GET /api/candidates/history
Authorization: Bearer <candidate_token>
```

History includes interviews matched by **email** (backward compat) and by **candidate_id** (set when the candidate accesses an interview via code lookup). Results are deduplicated and sorted by `created_at` descending.

Candidates can only see their own interviews.

---

## Services Overview

### Interview API (`interview-webapp-backend`)

Handles everything user-facing:
- Auth — register, login, JWT tokens, roles
- Organization registration with full verification workflow
- Verification document uploads (secure, disk-based)
- Super Admin org review and approval/rejection
- Subscription plan management and per-role limit enforcement
- Interviews — create, start, end, logs with candidate_id tracking
- AI Detection — YOLO/MediaPipe frame analysis (stub)
- WebRTC Signaling — offer/answer/ICE for peer-to-peer video
- Device Bridge — communicates with device_monitor_api
- Face Verification — InsightFace identity check (stub)
- Admin — branding, companies, recruiters, installer builds
- Real-time — Socket.IO events for live alerts

### Device Monitor API (`device-monitor-backend`)

Handles device telemetry from the candidate's machine:
- Receives reports from candidate-agent (USB, Wi-Fi, apps, heartbeat)
- Serves candidate device snapshots to interview_api
- Pushes live updates via Socket.IO

### Gateway (`gateway`)

API gateway / reverse proxy routing traffic to both services.

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

---

### Motor / PyMongo version error

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

## Project Team

| Area | Handled by |
|---|---|
| Interview API | Backend team |
| Device Monitor API | Backend team |
| Gateway | Infrastructure team |
| Frontend (web-portal, device-dashboard) | Frontend team |
| Electron desktop client | Desktop team |
| Candidate agent (.exe) | Desktop team |
