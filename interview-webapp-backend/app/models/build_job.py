from beanie import Document
from typing import Optional, Literal
from datetime import datetime, timezone


class BuildJob(Document):
    status: Literal["pending", "building", "done", "failed"] = "pending"
    log_tail: Optional[str] = None
    output_file: Optional[str] = None
    created_at: datetime = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "build_jobs"
