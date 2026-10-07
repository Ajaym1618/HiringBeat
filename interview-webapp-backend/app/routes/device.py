import hmac
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional
import httpx
from app.config import settings
from app.models.interview import Interview
from app.models.device_link import DeviceLink
from app.core.auth import get_current_user
from app.core.permissions import require_recruiter
from app.models.user import User
from app.socket_events import sio

router = APIRouter(prefix="/api/device", tags=["device"])


class LinkRequest(BaseModel):
    interview_code: str
    required: bool = False


class EventPayload(BaseModel):
    interview_code: str
    event: str
    data: Optional[dict] = None


class ApproveResumeRequest(BaseModel):
    interview_code: str


class GenerateTokenRequest(BaseModel):
    interview_code: str


@router.post("/link")
async def link_device(body: LinkRequest, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == body.interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    existing = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if existing:
        return {"device_link_id": str(existing.id), "existing": True}
    link = DeviceLink(
        interview_id=str(interview.id),
        required=body.required,
    )
    await link.insert()
    return {"device_link_id": str(link.id)}


@router.get("/status/{code}")
async def get_device_status(code: str, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link or not link.candidate_id:
        return {"linked": False}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.DEVICE_MONITOR_URL}/api/candidates/{link.candidate_id}",
                headers={"X-Dashboard-Key": settings.DEVICE_BRIDGE_KEY},
                timeout=5.0,
            )
        return resp.json()
    except Exception:
        return {"error": "Device monitor unreachable"}


@router.get("/pdf/{code}")
async def get_device_pdf(code: str, current_user: User = Depends(get_current_user)):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link or not link.candidate_id:
        raise HTTPException(status_code=404, detail="No device link found")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.DEVICE_MONITOR_URL}/api/candidates/{link.candidate_id}/pdf",
                headers={"X-Dashboard-Key": settings.DEVICE_BRIDGE_KEY},
                timeout=10.0,
            )
        from fastapi.responses import Response
        return Response(content=resp.content, media_type="application/pdf")
    except Exception:
        raise HTTPException(status_code=502, detail="Device monitor unreachable")


@router.post("/generate-token")
async def generate_resume_token(
    body: GenerateTokenRequest, current_user: User = Depends(get_current_user)
):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == body.interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link:
        raise HTTPException(status_code=404, detail="No device link")
    token = secrets.token_urlsafe(32)
    link.resume_token = token
    link.resume_token_issued_at = datetime.now(timezone.utc)
    await link.save()
    return {"resume_token": token}


@router.post("/approve-resume")
async def approve_resume(
    body: ApproveResumeRequest, current_user: User = Depends(get_current_user)
):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == body.interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link:
        raise HTTPException(status_code=404, detail="No device link")
    link.paused = False
    link.resume_requested = False
    await link.save()
    await sio.emit("interview_resumed", {"interview_code": body.interview_code}, room=body.interview_code)
    return {"resumed": True}


@router.get("/link-status/{code}")
async def link_status(code: str):
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link:
        return {"linked": False}
    return {
        "linked": True,
        "status": link.status,
        "paused": link.paused,
        "verified": link.verified,
        "required": link.required,
    }


@router.post("/event")
async def bridge_event(body: EventPayload, x_bridge_key: Optional[str] = Header(None)):
    # Timing-safe key comparison
    if not x_bridge_key or not hmac.compare_digest(
        x_bridge_key.encode(), settings.DEVICE_BRIDGE_KEY.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid bridge key")
    interview = await Interview.find_one(Interview.interview_code == body.interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    link = await DeviceLink.find_one(DeviceLink.interview_id == str(interview.id))
    if not link:
        raise HTTPException(status_code=404, detail="No device link")

    if body.event == "usb_alert":
        await sio.emit("device_usb_alert", body.data or {}, room=body.interview_code)
    elif body.event == "paused":
        link.paused = True
        await link.save()
        await sio.emit("interview_paused", {"interview_code": body.interview_code}, room=body.interview_code)
    elif body.event == "resume_requested":
        link.resume_requested = True
        await link.save()
    elif body.event == "status_update":
        status_val = (body.data or {}).get("status")
        if status_val in ("online", "offline"):
            link.status = status_val
            await link.save()
    return {"received": True}
