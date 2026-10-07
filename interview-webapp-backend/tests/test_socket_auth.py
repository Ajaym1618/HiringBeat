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
