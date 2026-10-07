from beanie import Document
from typing import Optional, Literal
from datetime import datetime, timezone


class DeviceLink(Document):
    interview_id: str
    candidate_id: Optional[str] = None  # device_monitor_api session ID
    status: Literal["online", "offline"] = "offline"
    paused: bool = False
    verified: bool = False
    resume_token: Optional[str] = None
    resume_token_issued_at: Optional[datetime] = None
    resume_requested: bool = False
    required: bool = False
    last_attempt_ok: Optional[bool] = None
    last_attempt_reason: Optional[str] = None
    created_at: datetime = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "device_links"
        indexes = ["interview_id"]
