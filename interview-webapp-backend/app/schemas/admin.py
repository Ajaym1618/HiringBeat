from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from app.schemas.validators import validate_email, validate_password, validate_name


class CreateRecruiterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: Literal["recruiter", "company_manager"] = "recruiter"
    company_id: str
    title: Optional[str] = None

    _validate_email = field_validator("email", mode="before")(classmethod(validate_email))
    _validate_password = field_validator("password", mode="before")(classmethod(validate_password))
    _validate_name = field_validator("name", mode="before")(classmethod(validate_name))


class UpdateAppConfigRequest(BaseModel):
    app_name: Optional[str] = None
    logo_path: Optional[str] = None
    candidate_about_text: Optional[str] = None
    recruiter_about_text: Optional[str] = None
    candidate_about_image_path: Optional[str] = None
    recruiter_about_image_path: Optional[str] = None
