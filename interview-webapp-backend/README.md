# InterBeat Interview API

Core backend service for the InterBeat remote proctoring platform.

- **Port:** 5000
- **Database:** `interbeat_interview` (MongoDB)
- **Swagger UI:** http://localhost:5000/docs

---

## Setup

> Make sure you have set up the root `.env` file first. See the [root README](../README.md).

```powershell
# From inside this folder
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 5000
```

---

## API Endpoints

### Auth — `/api/auth`
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/companies` | Public | List active companies (for login picker) |
| POST | `/register` | Public (20/hr) | Candidate self-registration |
| POST | `/login` | Public (20/min) | Login, returns JWT token |
| GET | `/me` | JWT | Get current user info |

### Interviews — `/api/interviews`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/` | Recruiter | Create interview |
| GET | `/` | JWT | List interviews (filtered by role) |
| GET | `/code/{code}` | Public | Get interview by join code |
| GET | `/{id}` | JWT | Get interview by ID |
| POST | `/{id}/start` | Recruiter | Start interview |
| POST | `/{id}/end` | Recruiter | End interview |
| DELETE | `/{id}` | Recruiter | Delete interview |
| GET | `/{id}/logs` | Recruiter-like | Get activity logs |

### Monitoring — `/api/monitoring`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/alert` | Public | Ingest detection alert |
| GET | `/images/{path}` | Public | Serve screenshot image |
| GET | `/logs/{code}` | Recruiter | Get logs by interview code |

### Detection — `/api/monitoring`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/detect` | Public | Run AI detection on base64 frame |

### WebRTC Signaling — `/api/media`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/offer/{code}` | Public | Store SDP offer |
| GET | `/offer/{code}` | Public | Get SDP offer |
| POST | `/answer/{code}` | Public | Store SDP answer |
| GET | `/answer/{code}` | Public | Get SDP answer |
| POST | `/ice/{code}` | Public | Add ICE candidate |
| GET | `/ice/{code}` | Public | Get ICE candidates |

### Device Bridge — `/api/device`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/link` | Recruiter | Link interview to device session |
| GET | `/status/{code}` | Recruiter | Get device status + confidence score |
| GET | `/pdf/{code}` | Recruiter | Get device report PDF |
| POST | `/generate-token` | Recruiter | Generate resume token |
| POST | `/approve-resume` | Recruiter | Approve candidate resume |
| GET | `/link-status/{code}` | Public | Get link status (for candidate) |
| POST | `/event` | Bridge Key | Receive event from device_monitor_api |

### Face Verification — `/api/face`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/reference` | Recruiter | Capture reference photo |
| GET | `/reference/{code}` | Public | Check if reference exists |
| POST | `/verify` | Recruiter | Verify candidate identity |

### Admin — `/api/admin`
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/app-config/public` | Public | Get public branding config |
| GET | `/app-config` | Super Admin | Get full branding config |
| PUT | `/app-config` | Super Admin | Update branding |
| GET | `/companies` | Super Admin | List all companies |
| POST | `/companies` | Super Admin | Create company |
| PATCH | `/companies/{id}` | Super Admin | Update company status |
| GET | `/recruiters` | Super Admin | List recruiters |
| POST | `/recruiters` | Super Admin | Create recruiter/manager |
| DELETE | `/recruiters/{id}` | Super Admin | Delete recruiter |
| GET | `/recruiters/{id}/interviews` | Super Admin | List recruiter's interviews |
| GET | `/deployment-status` | Super Admin | Check deployment config |
| POST | `/build-app` | Super Admin | Trigger installer build |
| GET | `/build-status/{job_id}` | Super Admin | Check build status |
| GET | `/download-installer` | Super Admin | Download installer |

### Company Team — `/api/company`
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/team` | Company Manager | List team recruiters |
| POST | `/team` | Company Manager | Add recruiter to team |
| DELETE | `/team/{user_id}` | Company Manager | Remove recruiter |

---

## Roles

| Role | Can Self-Register | Key Permissions |
|---|---|---|
| `candidate` | Yes | Join interview by code |
| `recruiter` | No | Create, run, monitor interviews |
| `company_manager` | No | Manage recruiters, view-only interviews |
| `super_admin` | No (bootstrapped) | Branding, companies, installer builds |

---

## Socket.IO Events

Connect to `http://localhost:5000` with Socket.IO.

| Event | Direction | Description |
|---|---|---|
| `join_room` | Client → Server | Join interview room |
| `leave_room` | Client → Server | Leave interview room |
| `candidate_ready` | Client → Room | Candidate camera ready |
| `phone_ready` | Client → Room | Phone camera ready |
| `recruiter_present` | Client → Room | Recruiter opened monitor |
| `webrtc_offer` | Client → Room | WebRTC SDP offer relay |
| `webrtc_answer` | Client → Room | WebRTC SDP answer relay |
| `webrtc_ice` | Client → Room | WebRTC ICE candidate relay |
| `chat_message` | Client → Room | In-session chat |
| `interview_started` | Server → Room | Interview started |
| `interview_ended` | Server → Room | Interview ended |
| `detection_alert` | Server → Room | AI detection alert |
| `face_verification` | Server → Room | Face verification result |
| `device_usb_alert` | Server → Room | USB device event |
| `interview_paused` | Server → Room | Interview paused |
| `interview_resumed` | Server → Room | Interview resumed |
