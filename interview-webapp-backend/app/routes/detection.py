from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/monitoring", tags=["detection"])


class DetectRequest(BaseModel):
    interview_code: str
    frame_b64: str  # base64-encoded JPEG/PNG frame
    timestamp: Optional[str] = None


@router.post("/detect")
async def detect(body: DetectRequest):
    """
    STUB — YOLO / MediaPipe inference placeholder.
    The AI team will replace this body with real model loading.
    Returns a mock detection response matching the expected production schema.
    """
    return {
        "interview_code": body.interview_code,
        "timestamp": body.timestamp,
        "detections": {
            "faces": [{"bbox": [0, 0, 100, 100], "confidence": 0.99}],
            "hands": [],
            "phone_detected": False,
            "face_count": 1,
            "hand_count": 0,
        },
        "stub": True,
    }
