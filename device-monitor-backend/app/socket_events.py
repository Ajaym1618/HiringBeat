import logging
import socketio
from jose import jwt
from app.config import settings

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@sio.event
async def connect(sid, environ, auth=None):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("user_id")
            role = payload.get("role")
            logger.info("[device-monitor socket] authenticated connect: sid=%s user_id=%s role=%s", sid, user_id, role)
        except Exception:
            logger.warning("[device-monitor socket] rejected invalid token: sid=%s", sid)
            return False
    else:
        # No token — allow for backward compat (candidate agent, testing)
        logger.warning("[device-monitor socket] connect without auth token: sid=%s", sid)
    return True


@sio.event
async def disconnect(sid):
    logger.info("[device-monitor socket] disconnect: sid=%s", sid)


@sio.event
async def join_session(sid, data):
    """Client joins a session room to receive updates for a specific candidate session."""
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if session_id:
        await sio.enter_room(sid, f"session_{session_id}")
        await sio.emit("session_joined", {"session_id": session_id}, to=sid)


@sio.event
async def leave_session(sid, data):
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if session_id:
        await sio.leave_room(sid, f"session_{session_id}")
