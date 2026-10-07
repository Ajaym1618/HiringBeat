from beanie import Document
from typing import Optional, List, Literal
from datetime import datetime, timezone


class CandidateSession(Document):
    candidate_name: str
    hostname: Optional[str] = None
    device: Optional[dict] = None  # OS, CPU, RAM, cameras, browsers, bluetooth, usb_devices, wifi, monitors, running_apps
    usb_events: List[dict] = []
    wifi_events: List[dict] = []
    close_events: List[dict] = []
    status: Literal["online", "offline"] = "online"
    last_seen: datetime = None
    created_at: datetime = None

    def __init__(self, **data):
        now = datetime.now(timezone.utc)
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = now
        if "last_seen" not in data or data["last_seen"] is None:
            data["last_seen"] = now
        super().__init__(**data)

    class Settings:
        name = "candidate_sessions"
