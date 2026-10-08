"""
Tests for Device Monitor Socket.IO authentication and authorization.
Mock MongoDB calls and bridge HTTP calls — no real DB or network needed.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
from jose import jwt

import os
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DEVICE_BRIDGE_KEY", "test-bridge-key")
os.environ.setdefault("MONGO_URI_DEVICE", "mongodb://localhost:27017")

from app.socket_events import sio, _authenticated_sids  # noqa: E402
import app.socket_events as _se  # noqa: E402

SECRET = "test-secret-key"
BRIDGE_KEY = "test-bridge-key"
BRIDGE_BASE = "http://localhost:5000"


def make_token(user_id="user1", role="recruiter", company_id="companyA", secret=SECRET, expired=False, include_company=True):
    exp = datetime.now(timezone.utc) + (timedelta(seconds=-1) if expired else timedelta(hours=1))
    payload = {"user_id": user_id, "role": role, "exp": exp}
    if include_company and company_id is not None:
        payload["company_id"] = company_id
    return jwt.encode(payload, secret, algorithm="HS256")


class FakeSession:
    def __init__(self, session_id="sess1"):
        self.id = session_id


# ---------------------------------------------------------------------------
# Connect — JWT checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_no_token():
    """Connect with no auth must be rejected."""
    _authenticated_sids.clear()
    result = await sio.handlers["/"]["connect"]("sid_no_auth", {}, None)
    assert result is False


@pytest.mark.asyncio
async def test_connect_invalid_jwt():
    """Connect with a bad token string must be rejected."""
    _authenticated_sids.clear()
    result = await sio.handlers["/"]["connect"]("sid_bad", {}, {"token": "not.a.valid.jwt"})
    assert result is False


@pytest.mark.asyncio
async def test_connect_expired_jwt():
    """Connect with an expired JWT must be rejected."""
    _authenticated_sids.clear()
    token = make_token(expired=True)
    result = await sio.handlers["/"]["connect"]("sid_expired", {}, {"token": token})
    assert result is False


@pytest.mark.asyncio
async def test_connect_valid_jwt():
    """Connect with a valid JWT (recruiter, with company_id) must succeed and store info."""
    _authenticated_sids.clear()
    token = make_token(user_id="user1", role="recruiter", company_id="companyA")

    with patch("app.socket_events.settings") as mock_settings:
        mock_settings.SECRET_KEY = SECRET
        result = await sio.handlers["/"]["connect"]("sid_valid", {}, {"token": token})

    assert result is True
    assert "sid_valid" in _authenticated_sids
    assert _authenticated_sids["sid_valid"]["company_id"] == "companyA"
    assert _authenticated_sids["sid_valid"]["role"] == "recruiter"
    _authenticated_sids.clear()


@pytest.mark.asyncio
async def test_connect_no_user_id_in_token():
    """Connect with a JWT lacking user_id claim must be rejected."""
    _authenticated_sids.clear()
    payload = {"role": "recruiter", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    with patch("app.socket_events.settings") as mock_settings:
        mock_settings.SECRET_KEY = SECRET
        result = await sio.handlers["/"]["connect"]("sid_noid", {}, {"token": token})
    assert result is False


# ---------------------------------------------------------------------------
# join_session — unauthenticated gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_unauthenticated():
    """join_session from a sid not in _authenticated_sids must emit error."""
    _authenticated_sids.clear()
    _se._sid_registry if hasattr(_se, "_sid_registry") else None  # harmless check

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    with patch.object(sio, "emit", side_effect=fake_emit):
        await sio.handlers["/"]["join_session"]("sid_unauth", {"session_id": "sess1"})

    assert any(e[0] == "error" for e in emitted)


# ---------------------------------------------------------------------------
# join_session — role gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_candidate_rejected():
    """candidate role must never be allowed to join a monitoring session."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_cand"] = {"user_id": "c1", "role": "candidate", "company_id": None}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    with patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room):
        await sio.handlers["/"]["join_session"]("sid_cand", {"session_id": "sess1"})

    assert any(e[0] == "error" for e in emitted)
    assert entered_rooms == []
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — session existence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_nonexistent_session():
    """If CandidateSession.get returns None, must emit error 'session not found'."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_nosess"] = {"user_id": "r1", "role": "recruiter", "company_id": "companyA"}

    emitted = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit):
        MockSession.get = AsyncMock(return_value=None)
        await sio.handlers["/"]["join_session"]("sid_nosess", {"session_id": "nonexistent"})

    assert any(e[0] == "error" and "session not found" in e[1].get("error", "") for e in emitted)
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — bridge: 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_bridge_404():
    """Bridge returning 404 must reject the join with 'session not found' error."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_b404"] = {"user_id": "r1", "role": "recruiter", "company_id": "companyA"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_b404")

    # Build a mock httpx response with status_code 404
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_b404", {"session_id": "sess_b404"})

    assert any(e[0] == "error" and "session not found" in e[1].get("error", "") for e in emitted)
    assert entered_rooms == []
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — bridge: network error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_bridge_error():
    """Bridge raising httpx.RequestError must reject the join with a service-unavailable error message."""
    import httpx
    _authenticated_sids.clear()
    _authenticated_sids["sid_berr"] = {"user_id": "r1", "role": "recruiter", "company_id": "companyA"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_berr")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("unreachable"))

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_berr", {"session_id": "sess_berr"})

    # Must emit an error event
    error_events = [e for e in emitted if e[0] == "error"]
    assert len(error_events) >= 1, "Expected at least one 'error' event to be emitted"

    # Must contain a specific bridge-unavailable message
    error_messages = [e[1].get("error", "") for e in error_events]
    assert any("authorization service unavailable" in msg.lower() or "unavailable" in msg.lower() for msg in error_messages), (
        f"Expected bridge-unavailable message, got: {error_messages}"
    )

    assert entered_rooms == []
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — cross-company rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_cross_company_rejected():
    """Bridge returns companyA but user is companyB — must be rejected."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_cross"] = {"user_id": "r1", "role": "recruiter", "company_id": "companyB"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_cross")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"company_id": "companyA", "interview_code": "XYZ"})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_cross", {"session_id": "sess_cross"})

    assert any(e[0] == "error" and "not authorized" in e[1].get("error", "") for e in emitted)
    assert entered_rooms == []
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — own company allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_own_company_allowed():
    """Bridge returns companyA, user is companyA — must be allowed into the room."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_own"] = {"user_id": "r1", "role": "recruiter", "company_id": "companyA"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_own")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"company_id": "companyA", "interview_code": "XYZ"})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_own", {"session_id": "sess_own"})

    assert ("sid_own", "session_sess_own") in entered_rooms
    assert any(e[0] == "session_joined" for e in emitted)
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — super_admin bypasses company check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_super_admin_any_company_allowed():
    """super_admin must be allowed regardless of company_id mismatch."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_admin"] = {"user_id": "a1", "role": "super_admin", "company_id": "companyB"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_admin")

    # Bridge should NOT be called for super_admin — but if it is, return 200 anyway
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"company_id": "companyA", "interview_code": "XYZ"})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_admin", {"session_id": "sess_admin"})

    # super_admin must have entered the room
    assert ("sid_admin", "session_sess_admin") in entered_rooms
    assert any(e[0] == "session_joined" for e in emitted)
    # Bridge must NOT have been called for super_admin
    mock_client.get.assert_not_called()
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — company_manager own company allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_company_manager_own_company_allowed():
    """company_manager with matching company must be allowed."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_cm_ok"] = {"user_id": "m1", "role": "company_manager", "company_id": "companyA"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_cm_ok")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"company_id": "companyA", "interview_code": "XYZ"})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_cm_ok", {"session_id": "sess_cm_ok"})

    assert ("sid_cm_ok", "session_sess_cm_ok") in entered_rooms
    assert any(e[0] == "session_joined" for e in emitted)
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# join_session — company_manager cross-company rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_session_company_manager_cross_company_rejected():
    """company_manager from a different company must be rejected."""
    _authenticated_sids.clear()
    _authenticated_sids["sid_cm_bad"] = {"user_id": "m1", "role": "company_manager", "company_id": "companyB"}

    emitted = []
    entered_rooms = []

    async def fake_emit(event, data, to=None, room=None, skip_sid=None):
        emitted.append((event, data, to or room))

    async def fake_enter_room(sid, room):
        entered_rooms.append((sid, room))

    fake_session = FakeSession("sess_cm_bad")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"company_id": "companyA", "interview_code": "XYZ"})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.socket_events.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit), \
         patch.object(sio, "enter_room", side_effect=fake_enter_room), \
         patch("app.socket_events.httpx.AsyncClient", return_value=mock_client):
        MockSession.get = AsyncMock(return_value=fake_session)
        await sio.handlers["/"]["join_session"]("sid_cm_bad", {"session_id": "sess_cm_bad"})

    assert any(e[0] == "error" and "not authorized" in e[1].get("error", "") for e in emitted)
    assert entered_rooms == []
    _authenticated_sids.clear()


# ---------------------------------------------------------------------------
# Telemetry isolation: candidate_update uses room=f"session_{session_id}"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telemetry_isolation():
    """candidate_update must be emitted to a specific room, not broadcast."""
    from app.routes.report import handle_report, ReportPayload

    fake_session = FakeSession("test_isolation_sess")

    emitted_calls = []

    async def fake_emit(event, data, room=None, to=None, **kwargs):
        emitted_calls.append({"event": event, "room": room, "to": to})

    with patch("app.routes.report.CandidateSession") as MockSession, \
         patch.object(sio, "emit", side_effect=fake_emit):
        # Simulate a full report that triggers candidate_update
        MockSession.get = AsyncMock(return_value=fake_session)
        # Manually call the emit pattern used in report.py for quick_update
        fake_session.device = {}
        fake_session.status = "online"
        fake_session.last_seen = None

        async def fake_save(self=fake_session):
            pass
        fake_session.save = fake_save

        MockSession.get = AsyncMock(return_value=fake_session)

        payload = ReportPayload(
            type="quick_update",
            session_id="test_isolation_sess",
            running_apps=["chrome"],
        )
        await handle_report(payload)

    # Verify all emits to session rooms use the specific room kwarg
    session_emits = [c for c in emitted_calls if c.get("event") == "candidate_update"]
    assert len(session_emits) >= 1
    for call in session_emits:
        assert call["room"] == "session_test_isolation_sess", (
            f"Expected room='session_test_isolation_sess', got room={call['room']!r}"
        )
        assert call["to"] is None, f"Expected no 'to' broadcast, got to={call['to']!r}"
