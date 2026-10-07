import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from app.models.activity_log import ActivityLog
from app.models.interview import Interview
from app.core.auth import get_current_user
from app.core.permissions import require_recruiter_like
from app.models.user import User
from app.socket_events import sio
from fastapi import Depends
from app.config import settings

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


class AlertRequest(BaseModel):
    interview_code: str
    event_type: str
    description: Optional[str] = None
    face_count: Optional[int] = None
    hand_count: Optional[int] = None
    phone_detected: Optional[bool] = None
    confidence: Optional[float] = None
    image_path: Optional[str] = None


@router.post("/alert")
async def post_alert(body: AlertRequest):
    interview = await Interview.find_one(Interview.interview_code == body.interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    log = ActivityLog(
        interview_id=str(interview.id),
        event_type=body.event_type,
        description=body.description,
        face_count=body.face_count,
        hand_count=body.hand_count,
        phone_detected=body.phone_detected,
        confidence=body.confidence,
        image_path=body.image_path,
    )
    await log.insert()
    await sio.emit(
        "detection_alert",
        {
            "event_type": body.event_type,
            "description": body.description,
            "face_count": body.face_count,
            "phone_detected": body.phone_detected,
            "confidence": body.confidence,
        },
        room=body.interview_code,
    )
    return {"logged": True}


@router.get("/images/{path:path}")
async def serve_image(path: str):
    file_path = os.path.join(settings.UPLOAD_FOLDER, path)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)


@router.get("/logs/{code}")
async def get_logs_by_code(
    code: str,
    current_user: User = Depends(get_current_user),
):
    require_recruiter_like(current_user)
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    logs = await ActivityLog.find(ActivityLog.interview_id == str(interview.id)).to_list()
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
