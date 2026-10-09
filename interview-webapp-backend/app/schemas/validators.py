"""
Reusable field validators — import and use in any schema.

Usage (Pydantic v2 — requires classmethod() and mode='before'):
    from app.schemas.validators import validate_email, validate_password, validate_name

    class MySchema(BaseModel):
        email: str
        password: str
        name: str

        _validate_email = field_validator("email", mode="before")(classmethod(validate_email))
        _validate_password = field_validator("password", mode="before")(classmethod(validate_password))
        _validate_name = field_validator("name", mode="before")(classmethod(validate_name))
"""

import re

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"


def validate_email(cls, v: str) -> str:
    if not v or not v.strip():
        raise ValueError("Email is required")
    if not re.match(EMAIL_REGEX, v.strip()):
        raise ValueError("Invalid email address")
    return v.strip().lower()


def validate_password(cls, v: str) -> str:
    if not v or len(v.strip()) == 0:
        raise ValueError("Password is required")
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[0-9]", v):
        raise ValueError("Password must contain at least one number")
    return v


def validate_name(cls, v: str) -> str:
    if not v or len(v.strip()) < 2:
        raise ValueError("Name must be at least 2 characters")
    return v.strip()


def validate_optional_email(cls, v: str) -> str:
    """For optional email fields — only validates if a value is provided."""
    if v is None or v.strip() == "":
        return v
    if not re.match(EMAIL_REGEX, v.strip()):
        raise ValueError("Invalid email address")
    return v.strip().lower()


def validate_org_name(cls, v: str) -> str:
    """Validate organization name length and presence."""
    if not v or len(v.strip()) < 2:
        raise ValueError("Organization name must be at least 2 characters")
    if len(v.strip()) > 100:
        raise ValueError("Organization name must be 100 characters or less")
    return v.strip()


def validate_pan(cls, v: str) -> str:
    """Validate Indian PAN format: 5 uppercase letters, 4 digits, 1 uppercase letter."""
    if not v or not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', v.strip().upper()):
        raise ValueError("Invalid PAN format. Expected format: ABCDE1234F")
    return v.strip().upper()
