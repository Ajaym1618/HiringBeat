from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Literal
from datetime import datetime
import re
from app.schemas.validators import validate_email, validate_password, validate_name, validate_org_name, validate_pan


class OrgRegisterRequest(BaseModel):
    company_name: str
    work_email: str
    password: str
    phone_number: str

    _validate_company_name = field_validator("company_name", mode="before")(classmethod(validate_org_name))
    _validate_work_email = field_validator("work_email", mode="before")(classmethod(validate_email))
    _validate_password = field_validator("password", mode="before")(classmethod(validate_password))

    @field_validator("phone_number", mode="before")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("Phone number is required")
        stripped = str(v).strip()
        # Accept E.164 and common local formats: optional +, then 7–15 digits/spaces/hyphens/parens
        if not re.match(r"^\+?[0-9][0-9\s\-\(\)]{5,18}[0-9]$", stripped):
            raise ValueError("Invalid phone number format. Use E.164 (e.g. +919876543210) or a local number with 7-15 digits.")
        return stripped


class OrgProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    org_type: Optional[str] = None
    registration_number: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    registered_address: Optional[str] = None
    website: Optional[str] = None
    authorized_person_name: Optional[str] = None
    authorized_person_designation: Optional[str] = None
    authorized_person_email: Optional[str] = None
    authorized_person_phone: Optional[str] = None

    @field_validator("pan", mode="before")
    @classmethod
    def _validate_pan_optional(cls, v):
        if v is None:
            return v
        return validate_pan(cls, v)

    @field_validator("authorized_person_email", mode="before")
    @classmethod
    def _validate_auth_email_optional(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return v
        return validate_email(cls, v)

    @field_validator("authorized_person_phone", mode="before")
    @classmethod
    def _validate_auth_phone_optional(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return v
        stripped = str(v).strip()
        if not re.match(r"^\+?[0-9][0-9\s\-\(\)]{5,18}[0-9]$", stripped):
            raise ValueError("Invalid phone number format.")
        return stripped


class OrgProfileOut(BaseModel):
    id: str
    name: str
    status: str
    verification_status: str
    rejection_reason: Optional[str] = None
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
    subscription_status: Optional[str] = None
    verified_at: Optional[datetime] = None


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
