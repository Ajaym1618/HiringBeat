
from datetime import datetime, timezone
from typing import Any

from beanie import Document
from pydantic import Field


class WebsiteContent(Document):
    """Stores the public InterBeat website content."""

    key: str = "homepage"
    content: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Settings:
        name = "website_content"
