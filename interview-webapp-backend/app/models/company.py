from beanie import Document
from typing import Literal
from datetime import datetime, timezone


class Company(Document):
    name: str
    status: Literal["active", "inactive"] = "active"
    created_at: datetime = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "companies"
