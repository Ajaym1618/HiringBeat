import logging
import socketio
import httpx
from jose import jwt
from app.config import settings
from app.models.candidate_session import CandidateSession

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# sid -> authenticated user info
_authenticated_sids: dict[str, dict] = {}


@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if not token:
        logger.warning("[device-monitor socket] rejected connect: no auth token, sid=%s", sid)
        return False
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        role = payload.get("role")
        if user_id is None:
            logger.warning("[device-monitor socket] rejected connect: no user_id in token, sid=%s", sid)
            return False
        _authenticated_sids[sid] = {
            "user_id": user_id,
            "role": role,
            "company_id": payload.get("company_id"),
        }
        logger.info("[device-monitor socket] authenticated connect: sid=%s user_id=%s role=%s", sid, user_id, role)
        return True
    except Exception:
        logger.warning("[device-monitor socket] rejected invalid/expired token: sid=%s", sid)
        return False


@sio.event
async def disconnect(sid):
    _authenticated_sids.pop(sid, None)
    logger.info("[device-monitor socket] disconnect: sid=%s", sid)


@sio.event
async def join_session(sid, data):
    """Client joins a session room to receive updates for a specific candidate session."""
    # Must be authenticated
    if sid not in _authenticated_sids:
        await sio.emit("error", {"error": "not authenticated"}, to=sid)
        return

    user_info = _authenticated_sids[sid]
    role = user_info.get("role")

    # Only recruiters, company managers, and super admins may monitor sessions
    if role not in ("recruiter", "company_manager", "super_admin"):
        await sio.emit("error", {"error": "not authorized to monitor sessions"}, to=sid)
        return

    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not session_id:
        await sio.emit("error", {"error": "session_id required"}, to=sid)
        return

    # Verify the session exists in the DB
    session = await CandidateSession.get(session_id)
    if session is None:
        await sio.emit("error", {"error": "session not found"}, to=sid)
        return

    # Cross-company isolation: verify this session belongs to the user's company
    # via the Interview API bridge (session → DeviceLink → Interview → company_id)
    if role != "super_admin":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.BRIDGE_URL}/api/device/session-company/{session_id}",
                    headers={"X-Bridge-Key": settings.DEVICE_BRIDGE_KEY},
                )
            if resp.status_code == 404:
                await sio.emit("error", {"error": "session not found or not linked to an interview"}, to=sid)
                return
            if resp.status_code != 200:
                await sio.emit("error", {"error": "authorization check failed"}, to=sid)
                return
            session_company = resp.json()
            if str(session_company.get("company_id")) != str(user_info.get("company_id")):
                logger.warning(
                    "[device-monitor socket] cross-company join rejected: sid=%s user_company=%s session_company=%s",
                    sid, user_info.get("company_id"), session_company.get("company_id"),
                )
                await sio.emit("error", {"error": "not authorized for this session"}, to=sid)
                return
        except httpx.RequestError:
            await sio.emit("error", {"error": "authorization service unavailable"}, to=sid)
            return

    await sio.enter_room(sid, f"session_{session_id}")
    await sio.emit("session_joined", {"session_id": session_id}, to=sid)


@sio.event
async def leave_session(sid, data):
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if session_id:
        await sio.leave_room(sid, f"session_{session_id}")
