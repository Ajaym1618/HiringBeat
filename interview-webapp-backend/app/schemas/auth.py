from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from app.schemas.validators import validate_email, validate_password, validate_name


class RegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    phone_number: str
    # name is derived from first_name + last_name automatically
    role: Literal["candidate"] = "candidate"

    _validate_email = field_validator("email", mode="before")(classmethod(validate_email))
    _validate_password = field_validator("password", mode="before")(classmethod(validate_password))
    _validate_first_name = field_validator("first_name", mode="before")(classmethod(validate_name))
    _validate_last_name = field_validator("last_name", mode="before")(classmethod(validate_name))


class LoginRequest(BaseModel):
    email: str
    password: str
    role: Optional[str] = None
    company_id: Optional[str] = None

    _validate_email = field_validator("email", mode="before")(classmethod(validate_email))
    _validate_password = field_validator("password", mode="before")(classmethod(validate_password))


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    user_id: str
