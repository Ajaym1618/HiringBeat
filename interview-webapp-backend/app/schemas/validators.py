"""
Reusable field validators — import and use in any schema.

Usage:
    from app.schemas.validators import validate_email, validate_password, validate_name

    class MySchema(BaseModel):
        email: str
        password: str
        name: str

        _validate_email = field_validator("email")(validate_email)
        _validate_password = field_validator("password")(validate_password)
        _validate_name = field_validator("name")(validate_name)
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
