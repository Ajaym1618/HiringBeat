from datetime import datetime, timezone
from typing import Any

from beanie import Document
from pydantic import Field


class WebsiteContent(Document):
    """Stores a single section of the InterBeat website content."""

    section: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Settings:
        name = "sections"
