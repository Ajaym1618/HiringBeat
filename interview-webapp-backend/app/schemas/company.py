from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

# FIX 2: status Literal must stay in sync with Company.status in app/models/company.py.
# Both must be updated together whenever a new status value is added.
_STATUS_LITERAL = Literal["active", "inactive", "pending_verification", "rejected"]


class CreateCompanyRequest(BaseModel):
    name: str
    status: _STATUS_LITERAL = "active"


class PatchCompanyRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[_STATUS_LITERAL] = None


class CompanyOut(BaseModel):
    id: str
    name: str
    status: str
    verification_status: Optional[str] = None
    plan: Optional[str] = None
    interview_limit: Optional[int] = None
    seat_limit: Optional[int] = None
    subscription_expires_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    rejection_reason: Optional[str] = None
