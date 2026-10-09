import secrets
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.models.interview import Interview
from app.models.activity_log import ActivityLog
from app.schemas.interview import CreateInterviewRequest, InterviewOut
from app.core.auth import get_current_user
from app.core.permissions import (
    can_run_interviews, require_recruiter, require_recruiter_like,
    user_can_access_interview, is_recruiter_like
)
from app.models.user import User
from app.models.company import Company
from app.core.subscription import enforce_interview_limit
from app.socket_events import sio
from bson.errors import InvalidId
from datetime import datetime, timezone

router = APIRouter(prefix="/api/interviews", tags=["interviews"])

# Optional bearer for get_by_code
_optional_bearer = HTTPBearer(auto_error=False)


async def _get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> Optional[User]:
    """Return the authenticated user if a valid bearer token is present, else None."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials)
    except Exception:
        return None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_interview(
    body: CreateInterviewRequest,
    current_user: User = Depends(get_current_user),
):
    require_recruiter(current_user)

    # --- subscription check (FR-5) ---
    if not current_user.company_id:
        raise HTTPException(status_code=403, detail="No company associated with user")
    try:
        company = await Company.get(current_user.company_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=403, detail="Company not found")
    if not company:
        raise HTTPException(status_code=403, detail="Company not found")

    # Use new plan-based enforcement — no legacy fallback allowed
    await enforce_interview_limit(company)

    code = secrets.token_hex(4).upper()  # 8-char hex
    interview = Interview(
        title=body.title,
        description=body.description,
        interview_code=code,
        recruiter_id=str(current_user.id),
        company_id=str(current_user.company_id),
        candidate_name=body.candidate_name,
        candidate_email=body.candidate_email,
        scheduled_at=body.scheduled_at,
    )
    await interview.insert()
    return {"id": str(interview.id), "interview_code": code}


@router.get("/")
async def list_interviews(current_user: User = Depends(get_current_user)):
    if current_user.role == "super_admin":
        interviews = await Interview.find_all().to_list()
    elif is_recruiter_like(current_user):
        interviews = await Interview.find(Interview.company_id == str(current_user.company_id)).to_list()
    else:
        # candidate — not applicable per spec but return empty
        interviews = []
    return [{"id": str(i.id), "title": i.title, "status": i.status, "interview_code": i.interview_code} for i in interviews]


@router.get("/code/{code}")
async def get_by_code(
    code: str,
    current_user: Optional[User] = Depends(_get_optional_user),
):
    """Look up an interview by code. Securely associates candidate_id when authenticated."""
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Secure candidate association — only associate if:
    # 1. user is authenticated as a candidate
    # 2. interview has no existing candidate_id (don't overwrite)
    # 3. candidate's email matches interview.candidate_email (or no email was pre-assigned)
    if current_user and current_user.role == "candidate":
        if interview.candidate_id and interview.candidate_id != str(current_user.id):
            # Interview already claimed by a different candidate
            raise HTTPException(
                status_code=403,
                detail="This interview is assigned to a different candidate",
            )
        if not interview.candidate_id:
            # Only associate if email matches (when a specific candidate was pre-assigned)
            if interview.candidate_email and interview.candidate_email != current_user.email:
                raise HTTPException(
                    status_code=403,
                    detail="This interview is not assigned to your account",
                )
            # Safe to associate
            interview.candidate_id = str(current_user.id)
            await interview.save()

    return {"id": str(interview.id), "title": interview.title, "status": interview.status, "interview_code": code}


@router.get("/{interview_id}")
async def get_interview(interview_id: str, current_user: User = Depends(get_current_user)):
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not user_can_access_interview(current_user, interview):
        raise HTTPException(status_code=403, detail="Access denied")
    return {
        "id": str(interview.id),
        "title": interview.title,
        "description": interview.description,
        "interview_code": interview.interview_code,
        "status": interview.status,
        "recruiter_id": interview.recruiter_id,
        "company_id": interview.company_id,
        "candidate_name": interview.candidate_name,
        "candidate_email": interview.candidate_email,
        "candidate_id": interview.candidate_id,
        "started_at": interview.started_at,
        "ended_at": interview.ended_at,
        "scheduled_at": interview.scheduled_at,
        "face_reference_path": interview.face_reference_path,
        "created_at": interview.created_at,
    }


@router.post("/{interview_id}/start")
async def start_interview(interview_id: str, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not user_can_access_interview(current_user, interview):
        raise HTTPException(status_code=403, detail="Access denied")
    interview.status = "active"
    interview.started_at = datetime.now(timezone.utc)
    await interview.save()
    await sio.emit("interview_started", {"interview_id": interview_id}, room=interview.interview_code)
    return {"status": "active"}


@router.post("/{interview_id}/end")
async def end_interview(interview_id: str, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not user_can_access_interview(current_user, interview):
        raise HTTPException(status_code=403, detail="Access denied")
    interview.status = "completed"
    interview.ended_at = datetime.now(timezone.utc)
    await interview.save()
    await sio.emit("interview_ended", {"interview_id": interview_id}, room=interview.interview_code)
    return {"status": "completed"}


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview(interview_id: str, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not user_can_access_interview(current_user, interview):
        raise HTTPException(status_code=403, detail="Access denied")
    await interview.delete()


@router.get("/{interview_id}/logs")
async def get_logs(interview_id: str, current_user: User = Depends(get_current_user)):
    require_recruiter_like(current_user)
    logs = await ActivityLog.find(ActivityLog.interview_id == interview_id).to_list()
    return [
        {
            "id": str(log.id),
            "event_type": log.event_type,
            "description": log.description,
            "face_count": log.face_count,
            "hand_count": log.hand_count,
            "phone_detected": log.phone_detected,
            "confidence": log.confidence,
            "image_path": log.image_path,
            "timestamp": log.timestamp,
        }
        for log in logs
    ]
