from beanie import Document
from pydantic import EmailStr
from typing import Optional, Literal
from datetime import datetime, timezone


class Interview(Document):
    title: str
    description: Optional[str] = None
    interview_code: str
    recruiter_id: str
    company_id: str
    candidate_name: Optional[str] = None
    candidate_email: Optional[EmailStr] = None
    candidate_id: Optional[str] = None
    status: Literal["scheduled", "active", "completed"] = "scheduled"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    face_reference_path: Optional[str] = None
    created_at: datetime = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "interviews"
        indexes = ["interview_code", "recruiter_id", "company_id"]
