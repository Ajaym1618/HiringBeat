from beanie import Document
from pydantic import EmailStr
from typing import Optional, Literal
from datetime import datetime, timezone


class User(Document):
    email: EmailStr
    password_hash: str
    name: str
    role: Literal["candidate", "recruiter", "company_manager", "super_admin"]
    company_id: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "users"
        indexes = ["email"]
