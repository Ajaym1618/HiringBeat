"""
Tests for the three API consolidation changes:
  1. PATCH-only approve/reject org routes (CHANGE 1 — no direct test needed; covered by test_org_features.py)
  2. GET /api/interviews/join/{code} — combined candidate initialization (CHANGE 2)
  3. POST /api/monitoring/alerts — batch alert ingestion (CHANGE 3)

All tests use AsyncMock/patch — no real MongoDB connection required.
"""
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("DEVICE_BRIDGE_KEY", "test-bridge-key")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Fake model helpers
# ---------------------------------------------------------------------------

class FakeInterview:
    def __init__(
        self,
        interview_id="int1",
        interview_code="ABCD1234",
        title="Test",
        status="scheduled",
        candidate_name="Alice",
        scheduled_at=None,
        recruiter_id="rec1",
        face_reference_path=None,
    ):
        self.id = interview_id
        self.interview_code = interview_code
        self.title = title
        self.status = status
        self.candidate_name = candidate_name
        self.scheduled_at = scheduled_at
        self.recruiter_id = recruiter_id
        self.face_reference_path = face_reference_path


class FakeDeviceLink:
    def __init__(
        self,
        interview_id="int1",
        required=True,
        verified=False,
        paused=False,
        last_attempt_ok=None,
    ):
        self.interview_id = interview_id
        self.required = required
        self.verified = verified
        self.paused = paused
        self.last_attempt_ok = last_attempt_ok


# ---------------------------------------------------------------------------
# CHANGE 2 — GET /api/interviews/join/{code}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_join_valid_code_returns_interview_and_device_status():
    """Valid code with an existing device link returns full interview + device_link."""
    from app.routes.interviews import join_interview
    from app.models.interview import Interview as InterviewModel
    from app.models.device_link import DeviceLink as DeviceLinkModel

    fake_interview = FakeInterview()
    fake_device_link = FakeDeviceLink(required=True, verified=False)

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=fake_interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True), \
         patch.object(DeviceLinkModel, "find_one", new_callable=AsyncMock, return_value=fake_device_link, create=True), \
         patch.object(DeviceLinkModel, "interview_id", new=MagicMock(), create=True):
        result = await join_interview(code="ABCD1234")

    assert "interview" in result
    assert result["interview"]["id"] == "int1"
    assert result["interview"]["interview_code"] == "ABCD1234"
    assert result["interview"]["title"] == "Test"
    assert result["interview"]["status"] == "scheduled"
    assert result["interview"]["candidate_name"] == "Alice"
    assert result["interview"]["scheduled_at"] is None

    assert "device_link" in result
    assert result["device_link"]["required"] is True
    assert result["device_link"]["verified"] is False


@pytest.mark.asyncio
async def test_join_invalid_code_returns_404():
    """Unknown code must raise HTTPException 404."""
    from app.routes.interviews import join_interview
    from app.models.interview import Interview as InterviewModel

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=None, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True):
        with pytest.raises(HTTPException) as exc_info:
            await join_interview(code="BADCODE")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_join_no_device_link_returns_null_device_status():
    """When no DeviceLink exists for the interview, device_link must be None."""
    from app.routes.interviews import join_interview
    from app.models.interview import Interview as InterviewModel
    from app.models.device_link import DeviceLink as DeviceLinkModel

    fake_interview = FakeInterview()

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=fake_interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True), \
         patch.object(DeviceLinkModel, "find_one", new_callable=AsyncMock, return_value=None, create=True), \
         patch.object(DeviceLinkModel, "interview_id", new=MagicMock(), create=True):
        result = await join_interview(code="ABCD1234")

    assert result["device_link"] is None


@pytest.mark.asyncio
async def test_join_does_not_return_sensitive_fields():
    """Response must NOT include recruiter_id or face_reference_path."""
    from app.routes.interviews import join_interview
    from app.models.interview import Interview as InterviewModel
    from app.models.device_link import DeviceLink as DeviceLinkModel

    fake_interview = FakeInterview(recruiter_id="rec_secret", face_reference_path="/uploads/face.jpg")

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=fake_interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True), \
         patch.object(DeviceLinkModel, "find_one", new_callable=AsyncMock, return_value=None, create=True), \
         patch.object(DeviceLinkModel, "interview_id", new=MagicMock(), create=True):
        result = await join_interview(code="ABCD1234")

    assert "recruiter_id" not in result["interview"]
    assert "face_reference_path" not in result["interview"]


# ---------------------------------------------------------------------------
# CHANGE 3 — POST /api/monitoring/alerts (batch)
# ---------------------------------------------------------------------------

def _make_alert_request(code: str = "ABCD1234"):
    from app.routes.monitoring import AlertRequest
    return AlertRequest(
        interview_code=code,
        event_type="face_count",
        description="Test alert",
        face_count=1,
        phone_detected=False,
        confidence=0.95,
    )


@pytest.mark.asyncio
async def test_batch_alerts_valid_processes_all():
    """Two valid alerts must both be processed with no errors."""
    from app.routes.monitoring import post_alerts_batch, BatchAlertRequest
    from app.models.interview import Interview as InterviewModel

    alert1 = _make_alert_request("CODE1")
    alert2 = _make_alert_request("CODE2")

    fake_interview = FakeInterview()
    fake_log = MagicMock()
    fake_log.insert = AsyncMock()

    with patch.object(InterviewModel, "find_one", new_callable=AsyncMock, return_value=fake_interview, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True), \
         patch("app.routes.monitoring.ActivityLog", return_value=fake_log), \
         patch("app.routes.monitoring.sio.emit", new_callable=AsyncMock):
        result = await post_alerts_batch(body=BatchAlertRequest(alerts=[alert1, alert2]))

    assert result == {"processed": 2, "errors": []}


@pytest.mark.asyncio
async def test_batch_alerts_exceeds_limit_returns_422():
    """More than 10 alerts must raise HTTPException 422."""
    from app.routes.monitoring import post_alerts_batch, BatchAlertRequest

    alerts = [_make_alert_request() for _ in range(11)]

    with pytest.raises(HTTPException) as exc_info:
        await post_alerts_batch(body=BatchAlertRequest(alerts=alerts))

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_batch_alerts_partial_invalid_returns_partial_success():
    """When one code is valid and the other is not found, processed=1 and errors has index=1."""
    from app.routes.monitoring import post_alerts_batch, BatchAlertRequest
    from app.models.interview import Interview as InterviewModel

    alert_valid = _make_alert_request("GOOD01")
    alert_bad = _make_alert_request("BADCODE")

    fake_interview = FakeInterview()
    fake_log = MagicMock()
    fake_log.insert = AsyncMock()

    # Return interview for first call, None for second
    find_one_mock = AsyncMock(side_effect=[fake_interview, None])

    with patch.object(InterviewModel, "find_one", find_one_mock, create=True), \
         patch.object(InterviewModel, "interview_code", new=MagicMock(), create=True), \
         patch("app.routes.monitoring.ActivityLog", return_value=fake_log), \
         patch("app.routes.monitoring.sio.emit", new_callable=AsyncMock):
        result = await post_alerts_batch(body=BatchAlertRequest(alerts=[alert_valid, alert_bad]))

    assert result["processed"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["index"] == 1


@pytest.mark.asyncio
async def test_batch_alerts_empty_list():
    """Empty alert list must return processed=0 and no errors."""
    from app.routes.monitoring import post_alerts_batch, BatchAlertRequest

    result = await post_alerts_batch(body=BatchAlertRequest(alerts=[]))

    assert result == {"processed": 0, "errors": []}
