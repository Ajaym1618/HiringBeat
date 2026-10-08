import logging
import socketio
from jose import jwt
from app.config import settings
from app.models.user import User
from app.models.interview import Interview

logger = logging.getLogger(__name__)

# Shared AsyncServer instance — imported by main.py and routes that need to emit
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# sid -> interview_code registry
_sid_registry: dict[str, str] = {}

# sid -> authenticated user info
_authenticated_sids: dict[str, dict] = {}


@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if not token:
        logger.warning("[socket] rejected connect: no auth token, sid=%s", sid)
        return False
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        role = payload.get("role")
        if user_id is None:
            logger.warning("[socket] rejected connect: no user_id in token, sid=%s", sid)
            return False
        user = await User.get(user_id)
        if user is None:
            logger.warning("[socket] rejected connect: user not found user_id=%s sid=%s", user_id, sid)
            return False
        _authenticated_sids[sid] = {
            "user_id": user_id,
            "role": role,
            "company_id": str(user.company_id) if user.company_id else None,
            "email": user.email,
        }
        logger.info("[socket] authenticated connect: sid=%s user_id=%s role=%s", sid, user_id, role)
        return True
    except Exception:
        logger.warning("[socket] rejected connect: invalid/expired token, sid=%s", sid)
        return False


@sio.event
async def disconnect(sid):
    _sid_registry.pop(sid, None)
    _authenticated_sids.pop(sid, None)
    logger.info("[socket] disconnect: sid=%s", sid)


@sio.event
async def join_room(sid, data):
    # Must be authenticated
    if sid not in _authenticated_sids:
        await sio.emit("error", {"error": "not authenticated"}, to=sid)
        return

    user_info = _authenticated_sids[sid]
    interview_code = data.get("interview_code") if isinstance(data, dict) else None
    if not interview_code:
        await sio.emit("error", {"error": "interview_code required"}, to=sid)
        return

    # Fetch interview from DB
    interview = await Interview.find_one(Interview.interview_code == interview_code)
    if interview is None:
        await sio.emit("error", {"error": "interview not found"}, to=sid)
        return

    # Authorization logic
    role = user_info.get("role")
    if role == "super_admin":
        pass  # super_admin can access any interview
    elif role in ("recruiter", "company_manager"):
        if user_info.get("company_id") != str(interview.company_id):
            logger.warning(
                "[socket] cross-company join rejected: sid=%s company=%s interview_company=%s",
                sid, user_info.get("company_id"), interview.company_id,
            )
            await sio.emit("error", {"error": "not authorized for this interview"}, to=sid)
            return
    elif role == "candidate":
        if interview.candidate_email != user_info.get("email"):
            logger.warning(
                "[socket] candidate join rejected: sid=%s email=%s interview_candidate=%s",
                sid, user_info.get("email"), interview.candidate_email,
            )
            await sio.emit("error", {"error": "not authorized for this interview"}, to=sid)
            return
    else:
        await sio.emit("error", {"error": "not authorized"}, to=sid)
        return

    await sio.enter_room(sid, interview_code)
    _sid_registry[sid] = interview_code
    await sio.emit("room_joined", {"interview_code": interview_code}, to=sid)


@sio.event
async def leave_room(sid, data):
    code = data.get("interview_code") if isinstance(data, dict) else None
    if code:
        # Only leave the room if this sid is actually registered to it
        if _sid_registry.get(sid) != code:
            return
        await sio.leave_room(sid, code)
        _sid_registry.pop(sid, None)


@sio.event
async def candidate_ready(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    user_info = _authenticated_sids[sid]
    if user_info.get("role") != "candidate":
        logger.warning("[socket] candidate_ready rejected: non-candidate role=%s sid=%s", user_info.get("role"), sid)
        await sio.emit("error", {"error": "only candidates may send this event"}, to=sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("candidate_ready", data, room=code, skip_sid=sid)


@sio.event
async def phone_ready(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    user_info = _authenticated_sids[sid]
    if user_info.get("role") != "candidate":
        logger.warning("[socket] phone_ready rejected: non-candidate role=%s sid=%s", user_info.get("role"), sid)
        await sio.emit("error", {"error": "only candidates may send this event"}, to=sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("phone_ready", data, room=code, skip_sid=sid)


@sio.event
async def recruiter_present(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    user_info = _authenticated_sids[sid]
    if user_info.get("role") not in ("recruiter", "company_manager", "super_admin"):
        logger.warning("[socket] recruiter_present rejected: role=%s sid=%s", user_info.get("role"), sid)
        await sio.emit("error", {"error": "not authorized"}, to=sid)
        return
    code = _sid_registry.get(sid)
    if not code:
        await sio.emit("error", {"error": "not in a room"}, to=sid)
        return
    await sio.emit("recruiter_present", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_offer(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_offer", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_answer(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_answer", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_ice(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_ice", data, room=code, skip_sid=sid)


@sio.event
async def chat_message(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("chat_message", data, room=code, skip_sid=sid)


@sio.event
async def interview_started(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    user_info = _authenticated_sids[sid]
    if user_info.get("role") not in ("recruiter", "super_admin"):
        logger.warning("[socket] interview_started rejected: role=%s sid=%s", user_info.get("role"), sid)
        await sio.emit("error", {"error": "only recruiters may control the interview"}, to=sid)
        return
    code = _sid_registry.get(sid)
    if not code:
        await sio.emit("error", {"error": "not in a room"}, to=sid)
        return
    await sio.emit("interview_started", data, room=code)


@sio.event
async def interview_ended(sid, data):
    if sid not in _authenticated_sids:
        logger.warning("[socket] unauthenticated event from sid=%s", sid)
        return
    user_info = _authenticated_sids[sid]
    if user_info.get("role") not in ("recruiter", "super_admin"):
        logger.warning("[socket] interview_ended rejected: role=%s sid=%s", user_info.get("role"), sid)
        await sio.emit("error", {"error": "only recruiters may control the interview"}, to=sid)
        return
    code = _sid_registry.get(sid)
    if not code:
        await sio.emit("error", {"error": "not in a room"}, to=sid)
        return
    await sio.emit("interview_ended", data, room=code)
