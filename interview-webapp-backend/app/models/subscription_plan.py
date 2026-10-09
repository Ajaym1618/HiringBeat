from beanie import Document
from typing import Optional
from datetime import datetime, timezone


class SubscriptionPlan(Document):
    plan_name: str
    max_admins: int
    max_recruiters: int
    max_interviews: int
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __init__(self, **data):
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now(timezone.utc)
        super().__init__(**data)

    class Settings:
        name = "subscription_plans"
