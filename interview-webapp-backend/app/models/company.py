from beanie import Document
from typing import Literal, Optional
from datetime import datetime, timezone


class Company(Document):
    name: str
    status: Literal["active", "inactive", "pending_verification", "rejected"] = "active"
    created_at: Optional[datetime] = None

    # --- Verification fields ---
    # verification_status defaults to "approved" so all existing admin-created companies
    # already satisfy approval state without migration.
    verification_status: Literal["pending", "approved", "rejected"] = "approved"
    rejection_reason: Optional[str] = None
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None

    # --- Legacy subscription fields (kept for backward compat with existing tests) ---
    plan: Literal["free", "basic", "pro"] = "free"
    interview_limit: int = 5
    seat_limit: int = 3
    subscription_expires_at: Optional[datetime] = None

    # --- New subscription fields (GAP 5) ---
    subscription_plan_id: Optional[str] = None
    subscription_status: Literal["active", "inactive", "expired"] = "inactive"
    subscription_started_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None

    # --- New org identity fields (GAP 1) ---
    org_type: Optional[str] = None
    registration_number: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    registered_address: Optional[str] = None
    website: Optional[str] = None
    official_phone: Optional[str] = None
    authorized_person_name: Optional[str] = None
    authorized_person_designation: Optional[str] = None
    authorized_person_email: Optional[str] = None
    authorized_person_phone: Optional[str] = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "companies"
