"""
Tests for Interview Socket.IO authentication and authorization.
Mock MongoDB calls — no real DB connection needed.
"""
import pytest
from unittest.mock import AsyncMock, patch
from jose import jwt

import os
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DEVICE_BRIDGE_KEY", "test-bridge-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from app.socket_events import sio, _authenticated_sids  # noqa: E402

SECRET = "test-secret-key"


def make_token(user_id="user1", role="recruiter", secret=SECRET, expired=False):
    from datetime import datetime, timedelta, timezone
    exp = datetime.now(timezone.utc) + (timedelta(seconds=-1) if expired else timedelta(hours=1))
    return jwt.encode({"user_id": user_id, "role": role, "exp": exp}, secret, algorithm="HS256")


class FakeUser:
    def __init__(self, user_id="user1", role="recruiter", company_id="company1", email="r@test.com"):
        self.id = user_id
        self.role = role
        self.company_id = company_id
        self.email = email


class FakeInterview:
    def __init__(self, company_id="company1", candidate_email="c@test.com", status="scheduled"):
        self.company_id = company_id
        self.candidate_email = candidate_email
        self.status = status


@pytest.mark.asyncio
async def test_connect_no_auth():
    """Connection without auth token must be rejected."""
    _authenticated_sids.clear()
    result = await sio.handlers["/"]["connect"]("sid_no_auth", {}, None)
    assert result is False


@pytest.mark.asyncio
async def test_connect_invalid_jwt():
    """Connection with an invalid JWT must be rejected."""
    _authenticated_sids.clear()
    result = await sio.handlers["/"]["connect"]("sid_bad", {}, {"token": "not.a.jwt"})
    assert result is False


@pytest.mark.asyncio
async def test_connect_expired_jwt():
    """Connection with an expired JWT must be rejected."""
    _authenticated_sids.clear()
    token = make_token(expired=True)
    result = await sio.handlers["/"]["connect"]("sid_expired", {}, {"token": token})
    assert result is False


@pytest.mark.asyncio
async def test_connect_valid_jwt():
    """Connection with a valid JWT and existing user must succeed."""
    _authenticated_sids.clear()
    token = make_token(user_id="user1", role="recruiter")
    fake_user = FakeUser(user_id="user1", role="recruiter", company_id="company1")
    with patch("app.socket_events.User") as MockUser:
        MockUser.get = AsyncMock(return_value=fake_user)
        with patch("app.socket_events.settings") as mock_settings:
            mock_settings.SECRET_KEY = SECRET
            result = await sio.handlers["/"]["connect"]("sid_valid", {}, {"token": token})
    assert result is True
    _authenticated_sids.clear()


@pytest.mark.asyncio
async def test_connect_user_not_found():
    """Connection with valid JWT but non-existent user must be rejected."""
    _authenticated_sids.clear()
    token = make_token(user_id="ghost", role="recruiter")
    with patch("app.socket_events.User") as MockUser:
        MockUser.get = AsyncMock(return_value=None)
        with patch("app.socket_events.settings") as mock_settings:
            mock_settings.SECRET_KEY = SECRET
            result = await sio.handlers["/"]["connect"]("sid_ghost", {}, {"token": token})
    assert result is False


@pytest.mark.asyncio
async def test_join_room_not_authenticated():
    """join_room from unauthenticated sid must emit error and not join."""
    _authenticated_sids.clear()
    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        pytest.fail("enter_room should not be called for unauthenticated sid")

    with patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room):
        await sio.handlers["/"]["join_room"]("sid_unauthed", {"interview_code": "TESTCODE"})
    assert any(e[0] == "error" for e in emitted)


@pytest.mark.asyncio
async def test_join_room_cross_company_rejected():
    """A recruiter from company B cannot join an interview belonging to company A."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_cross"] = {
        "user_id": "u1",
        "role": "recruiter",
        "company_id": "companyB",
        "email": "r@b.com",
    }
    fake_interview = FakeInterview(company_id="companyA")
    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        pytest.fail("enter_room should not be called for cross-company")

    with patch("app.socket_events.Interview") as MockInterview, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room):
        MockInterview.find_one = AsyncMock(return_value=fake_interview)
        MockInterview.interview_code = None
        await sio.handlers["/"]["join_room"]("sid_cross", {"interview_code": "TESTCODE"})
    assert any(e[0] == "error" for e in emitted)
    _authenticated_sids.clear()


@pytest.mark.asyncio
async def test_join_room_authorized():
    """A recruiter from the correct company can join the interview room."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_ok"] = {
        "user_id": "u1",
        "role": "recruiter",
        "company_id": "companyA",
        "email": "r@a.com",
    }
    fake_interview = FakeInterview(company_id="companyA")
    entered_rooms = []
    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    with patch("app.socket_events.Interview") as MockInterview, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room):
        MockInterview.find_one = AsyncMock(return_value=fake_interview)
        MockInterview.interview_code = None
        await sio.handlers["/"]["join_room"]("sid_ok", {"interview_code": "TESTCODE"})
    assert ("sid_ok", "TESTCODE") in entered_rooms
    assert any(e[0] == "room_joined" for e in emitted)
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# ITEM 4: Event-level authorization tests
# ---------------------------------------------------------------------------

import app.socket_events as _se  # noqa: E402


@pytest.mark.asyncio
async def test_leave_room_wrong_code():
    """leave_room with wrong code must NOT remove the sid from the room."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_lr"] = {"user_id": "u1", "role": "recruiter", "company_id": "c1", "email": "r@c.com"}
    _se._sid_registry["sid_lr"] = "ROOM_A"

    leave_called = []

    async def fake_leave(sid, room):
        leave_called.append((sid, room))

    with patch.object(sio, "leave_room", side_effect=fake_leave):
        await sio.handlers["/"]["leave_room"]("sid_lr", {"interview_code": "ROOM_B"})

    assert ("sid_lr", "ROOM_B") not in leave_called
    assert _se._sid_registry.get("sid_lr") == "ROOM_A"
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_leave_room_correct_code():
    """leave_room with matching code must call sio.leave_room."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_lr2"] = {"user_id": "u1", "role": "recruiter", "company_id": "c1", "email": "r@c.com"}
    _se._sid_registry["sid_lr2"] = "ROOM_A"

    leave_called = []

    async def fake_leave(sid, room):
        leave_called.append((sid, room))

    with patch.object(sio, "leave_room", side_effect=fake_leave):
        await sio.handlers["/"]["leave_room"]("sid_lr2", {"interview_code": "ROOM_A"})

    assert ("sid_lr2", "ROOM_A") in leave_called
    assert _se._sid_registry.get("sid_lr2") is None
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_recruiter_present_by_candidate_rejected():
    """candidate role must NOT be allowed to send recruiter_present."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_rp1"] = {"user_id": "c1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    _se._sid_registry["sid_rp1"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["recruiter_present"]("sid_rp1", {})

    assert any(e[0] == "error" and e[1] == "sid_rp1" for e in emitted)
    assert all(e[0] != "recruiter_present" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_recruiter_present_by_recruiter_allowed():
    """recruiter role in a room must be allowed to send recruiter_present."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_rp2"] = {"user_id": "r1", "role": "recruiter", "company_id": "c1", "email": "r@t.com"}
    _se._sid_registry["sid_rp2"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["recruiter_present"]("sid_rp2", {})

    assert any(e[0] == "recruiter_present" and e[1] == "ROOM_X" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_candidate_ready_by_recruiter_rejected():
    """recruiter role must NOT be allowed to send candidate_ready."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_cr1"] = {"user_id": "r1", "role": "recruiter", "company_id": "c1", "email": "r@t.com"}
    _se._sid_registry["sid_cr1"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["candidate_ready"]("sid_cr1", {})

    assert any(e[0] == "error" for e in emitted)
    assert all(e[0] != "candidate_ready" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_candidate_ready_by_candidate_allowed():
    """candidate role in a room must be allowed to send candidate_ready."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_cr2"] = {"user_id": "c1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    _se._sid_registry["sid_cr2"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["candidate_ready"]("sid_cr2", {})

    assert any(e[0] == "candidate_ready" and e[1] == "ROOM_X" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_phone_ready_by_recruiter_rejected():
    """recruiter role must NOT be allowed to send phone_ready."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_pr1"] = {"user_id": "r1", "role": "recruiter", "company_id": "c1", "email": "r@t.com"}
    _se._sid_registry["sid_pr1"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["phone_ready"]("sid_pr1", {})

    assert any(e[0] == "error" for e in emitted)
    assert all(e[0] != "phone_ready" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_interview_started_by_candidate_rejected():
    """candidate role must NOT be allowed to send interview_started."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_is1"] = {"user_id": "c1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    _se._sid_registry["sid_is1"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["interview_started"]("sid_is1", {})

    assert any(e[0] == "error" and e[1] == "sid_is1" for e in emitted)
    assert all(e[0] != "interview_started" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_interview_started_by_recruiter_allowed():
    """recruiter role in a room must be allowed to send interview_started."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_is2"] = {"user_id": "r1", "role": "recruiter", "company_id": "c1", "email": "r@t.com"}
    _se._sid_registry["sid_is2"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["interview_started"]("sid_is2", {})

    assert any(e[0] == "interview_started" and e[1] == "ROOM_X" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_interview_ended_by_candidate_rejected():
    """candidate role must NOT be allowed to send interview_ended."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_ie1"] = {"user_id": "c1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    _se._sid_registry["sid_ie1"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["interview_ended"]("sid_ie1", {})

    assert any(e[0] == "error" for e in emitted)
    assert all(e[0] != "interview_ended" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_interview_ended_by_company_manager_rejected():
    """company_manager role must NOT be allowed to send interview_ended (recruiter-only)."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_ie2"] = {"user_id": "m1", "role": "company_manager", "company_id": "c1", "email": "m@t.com"}
    _se._sid_registry["sid_ie2"] = "ROOM_X"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["interview_ended"]("sid_ie2", {})

    assert any(e[0] == "error" for e in emitted)
    assert all(e[0] != "interview_ended" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_webrtc_offer_not_in_room_rejected():
    """Authenticated sid NOT in _sid_registry must NOT emit webrtc_offer to any room."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_wrt1"] = {"user_id": "u1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    # Deliberately NOT added to _sid_registry

    emitted_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        if room is not None:
            emitted_rooms.append(room)

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["webrtc_offer"]("sid_wrt1", {})

    assert emitted_rooms == [], f"Expected no room emit, got: {emitted_rooms}"
    _authenticated_sids.clear()


@pytest.mark.asyncio
async def test_chat_message_authorized_participant_passes():
    """Authenticated sid in _sid_registry must have chat_message emitted to the room."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    _authenticated_sids["sid_chat1"] = {"user_id": "u1", "role": "candidate", "company_id": None, "email": "c@t.com"}
    _se._sid_registry["sid_chat1"] = "ROOM_CHAT"

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["chat_message"]("sid_chat1", {"msg": "hello"})

    assert any(e[0] == "chat_message" and e[1] == "ROOM_CHAT" for e in emitted)
    _authenticated_sids.clear()
    _se._sid_registry.clear()


@pytest.mark.asyncio
async def test_event_unauthenticated_dropped():
    """Events from a sid not in _authenticated_sids must be silently dropped."""
    _authenticated_sids.clear()
    _se._sid_registry.clear()
    # Not adding to _authenticated_sids

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["chat_message"]("sid_unauth_drop", {"msg": "hack"})
        await sio.handlers["/"]["webrtc_offer"]("sid_unauth_drop", {})
        await sio.handlers["/"]["interview_started"]("sid_unauth_drop", {})

    # No emits to any room should have happened
    room_emits = [e for e in emitted if e[1] != "sid_unauth_drop"]
    assert room_emits == [], f"Expected no room emits, got: {room_emits}"
