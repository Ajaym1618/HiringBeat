import logging
import socketio
from jose import jwt
from app.config import settings

logger = logging.getLogger(__name__)

# Shared AsyncServer instance — imported by main.py and routes that need to emit
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# sid -> interview_code registry
_sid_registry: dict[str, str] = {}


@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("user_id")
            role = payload.get("role")
            logger.info("[socket] authenticated connect: sid=%s user_id=%s role=%s", sid, user_id, role)
        except Exception:
            logger.warning("[socket] rejected unauthenticated connect: sid=%s — invalid token", sid)
            return False
    else:
        # No token provided — allow for backward compatibility (candidate-agent, testing)
        logger.warning("[socket] connect without auth token: sid=%s", sid)
    return True


@sio.event
async def disconnect(sid):
    _sid_registry.pop(sid, None)
    print(f"[socket] disconnect: {sid}")


@sio.event
async def join_room(sid, data):
    code = data.get("interview_code")
    if code:
        await sio.enter_room(sid, code)
        _sid_registry[sid] = code
        await sio.emit("room_joined", {"interview_code": code}, to=sid)


@sio.event
async def leave_room(sid, data):
    code = data.get("interview_code")
    if code:
        await sio.leave_room(sid, code)
        _sid_registry.pop(sid, None)


@sio.event
async def candidate_ready(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("candidate_ready", data, room=code, skip_sid=sid)


@sio.event
async def phone_ready(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("phone_ready", data, room=code, skip_sid=sid)


@sio.event
async def recruiter_present(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("recruiter_present", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_offer(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_offer", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_answer(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_answer", data, room=code, skip_sid=sid)


@sio.event
async def webrtc_ice(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("webrtc_ice", data, room=code, skip_sid=sid)


@sio.event
async def chat_message(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("chat_message", data, room=code, skip_sid=sid)


@sio.event
async def interview_started(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("interview_started", data, room=code)


@sio.event
async def interview_ended(sid, data):
    code = _sid_registry.get(sid)
    if code:
        await sio.emit("interview_ended", data, room=code)
