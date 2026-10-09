from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
from app.schemas.validators import validate_email, validate_password, validate_name, validate_org_name, validate_pan


class OrgRegisterRequest(BaseModel):
    # Existing required fields (keep validators)
    org_name: str
    manager_name: str
    manager_email: str
    password: str

    # New required fields (GAP 1)
    org_type: str
    registered_address: str
    official_phone: str
    authorized_person_name: str
    authorized_person_designation: str
    authorized_person_email: str
    authorized_person_phone: str

    # New optional fields (GAP 1)
    registration_number: Optional[str] = None
    pan: str
    gstin: Optional[str] = None
    website: Optional[str] = None

    _validate_org_name = field_validator("org_name", mode="before")(classmethod(validate_org_name))
    _validate_manager_name = field_validator("manager_name", mode="before")(classmethod(validate_name))
    _validate_manager_email = field_validator("manager_email", mode="before")(classmethod(validate_email))
    _validate_password = field_validator("password", mode="before")(classmethod(validate_password))
    _validate_auth_email = field_validator("authorized_person_email", mode="before")(classmethod(validate_email))
    _validate_pan = field_validator("pan", mode="before")(classmethod(validate_pan))


class RejectOrgRequest(BaseModel):
    reason: str  # required (changed from Optional[str] = None per GAP 3)


class PatchSubscriptionRequest(BaseModel):
    # New plan-based fields (GAP 8)
    plan_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    # Legacy fields kept for backward compat with existing tests
    plan: Optional[Literal["free", "basic", "pro"]] = None
    interview_limit: Optional[int] = Field(default=None, ge=1)
    seat_limit: Optional[int] = Field(default=None, ge=1)
    subscription_expires_at: Optional[datetime] = None


class OrgDocumentOut(BaseModel):
    id: str
    company_id: str
    document_type: str
    file_name: str
    uploaded_at: Optional[datetime] = None
    uploaded_by: str
    verification_status: str


class UpdateRoleRequest(BaseModel):
    role: Literal["recruiter", "company_manager"]


class ManagerOut(BaseModel):
    id: str
    email: str
    name: str


class OrgPendingOut(BaseModel):
    id: str
    name: str
    status: str
    verification_status: str
    created_at: Optional[datetime] = None
    manager: Optional[ManagerOut] = None


class CandidateInterviewHistoryItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    interview_code: str
    status: str
    company_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    # recruiter_id and face_reference_path are intentionally omitted (FR-9.5)
