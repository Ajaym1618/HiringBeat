import os
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel
from app.models.interview import Interview
from app.core.auth import get_current_user
from app.core.permissions import require_recruiter
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/api/face", tags=["face_verify"])


class VerifyRequest(BaseModel):
    interview_code: str
    frame_b64: str


@router.post("/reference")
async def upload_reference(
    interview_code: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    require_recruiter(current_user)
    interview = await Interview.find_one(Interview.interview_code == interview_code)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    os.makedirs(settings.UPLOAD_FOLDER, exist_ok=True)
    filename = f"face_ref_{interview_code}.jpg"
    path = os.path.join(settings.UPLOAD_FOLDER, filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    interview.face_reference_path = path
    await interview.save()
    return {"stored": True, "path": path}


@router.get("/reference/{code}")
async def get_reference(code: str):
    interview = await Interview.find_one(Interview.interview_code == code)
    if not interview or not interview.face_reference_path:
        raise HTTPException(status_code=404, detail="No reference image")
    return {"path": interview.face_reference_path}


@router.post("/verify")
async def verify_face(
    body: VerifyRequest,
    current_user: User = Depends(get_current_user),
):
    require_recruiter(current_user)
    """
    STUB — InsightFace identity verification placeholder.
    The AI team will replace this body with real model loading.
    """
    return {
        "interview_code": body.interview_code,
        "match": True,
        "confidence": 0.98,
        "stub": True,
    }
