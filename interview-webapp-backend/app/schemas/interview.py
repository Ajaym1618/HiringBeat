from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from app.schemas.validators import validate_optional_email


class CreateInterviewRequest(BaseModel):
    title: str
    description: Optional[str] = None
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    scheduled_at: Optional[datetime] = None

    _validate_candidate_email = field_validator("candidate_email", mode="before")(classmethod(validate_optional_email))


class InterviewOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    interview_code: str
    recruiter_id: str
    company_id: str
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    face_reference_path: Optional[str] = None
    created_at: Optional[datetime] = None
