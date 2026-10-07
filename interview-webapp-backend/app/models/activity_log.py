from beanie import Document
from typing import Optional
from datetime import datetime, timezone


class ActivityLog(Document):
    interview_id: str
    event_type: str
    description: Optional[str] = None
    face_count: Optional[int] = None
    hand_count: Optional[int] = None
    phone_detected: Optional[bool] = None
    confidence: Optional[float] = None
    image_path: Optional[str] = None
    timestamp: datetime = None

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "activity_logs"
        indexes = ["interview_id"]
