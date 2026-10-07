import asyncio
import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime, timezone
from app.models.candidate_session import CandidateSession
from app.socket_events import sio
from app.config import settings

router = APIRouter(prefix="/api", tags=["report"])


async def _push_bridge_event(payload: dict) -> None:
    """Fire-and-forget HTTP push to interview-webapp-backend bridge endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{settings.BRIDGE_URL}/api/device/event",
                json=payload,
                headers={"X-Bridge-Key": settings.DEVICE_BRIDGE_KEY},
            )
    except Exception:  # noqa: BLE001
        pass  # Bridge push is best-effort — never crash the main flow

REPORT_TYPES = [
    "full", "quick_update", "usb_event",
    "wifi_change", "heartbeat", "app_closed", "connect"
]


class ReportPayload(BaseModel):
    type: Literal["full", "quick_update", "usb_event", "wifi_change", "heartbeat", "app_closed", "connect"]
    session_id: Optional[str] = None
    candidate_name: Optional[str] = None
    hostname: Optional[str] = None
    device: Optional[dict] = None
    usb_event: Optional[dict] = None
    wifi_event: Optional[dict] = None
    close_event: Optional[dict] = None
    running_apps: Optional[list] = None


@router.post("/report")
async def handle_report(body: ReportPayload):
    now = datetime.now(timezone.utc)

    if body.type == "connect":
        session = CandidateSession(
            candidate_name=body.candidate_name or "Unknown",
            hostname=body.hostname,
            device=body.device or {},
            status="online",
        )
        await session.insert()
        await sio.emit("candidate_update", {"session_id": str(session.id), "status": "online"}, room=f"session_{str(session.id)}")
        return {"session_id": str(session.id)}

    if not body.session_id:
        return {"error": "session_id required for this report type"}

    session = await CandidateSession.get(body.session_id)
    if not session:
        return {"error": "session not found"}

    session.last_seen = now

    if body.type == "full":
        if body.device:
            session.device = body.device
        session.status = "online"
        await session.save()
        await sio.emit("candidate_update", {
            "session_id": body.session_id,
            "device": session.device,
            "status": "online",
        }, room=f"session_{body.session_id}")

    elif body.type == "quick_update":
        if body.running_apps is not None:
            if session.device is None:
                session.device = {}
            session.device["running_apps"] = body.running_apps
        session.status = "online"
        await session.save()
        await sio.emit("candidate_update", {
            "session_id": body.session_id,
            "running_apps": body.running_apps,
        }, room=f"session_{body.session_id}")

    elif body.type == "usb_event":
        if body.usb_event:
            session.usb_events.append({**body.usb_event, "timestamp": now.isoformat()})
        await session.save()
        await sio.emit("usb_alert", {
            "session_id": body.session_id,
            "usb_event": body.usb_event,
        }, room=f"session_{body.session_id}")
        asyncio.create_task(_push_bridge_event({
            "type": "usb_event",
            "candidate_id": body.session_id,
            "candidate_name": session.candidate_name,
            "event": body.usb_event,
        }))

    elif body.type == "wifi_change":
        if body.wifi_event:
            session.wifi_events.append({**body.wifi_event, "timestamp": now.isoformat()})
        await session.save()

    elif body.type == "heartbeat":
        session.status = "online"
        await session.save()

    elif body.type == "app_closed":
        if body.close_event:
            session.close_events.append({**body.close_event, "timestamp": now.isoformat()})
        session.status = "offline"
        await session.save()
        asyncio.create_task(_push_bridge_event({
            "type": "app_closed",
            "candidate_id": body.session_id,
            "candidate_name": session.candidate_name,
        }))

    return {"ok": True}
