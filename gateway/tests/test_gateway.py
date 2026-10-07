"""Gateway tests — pytest + httpx + respx.

Run:
    cd gateway
    pip install -r requirements.txt respx==0.21.1 pytest==8.2.0 pytest-asyncio==0.23.6
    pytest tests/ -v
"""
import pytest
import respx
import httpx
from httpx import AsyncClient
from fastapi.testclient import TestClient

# Patch settings before importing app
import os
os.environ.setdefault("INTERVIEW_API_URL", "http://interview-api")
os.environ.setdefault("DEVICE_MONITOR_API_URL", "http://device-api")

from app.main import app  # noqa: E402

INTERVIEW_BASE = "http://interview-api"
DEVICE_BASE = "http://device-api"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def test_health_check():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gateway"}


# ---------------------------------------------------------------------------
# Interview API proxy
# ---------------------------------------------------------------------------
@respx.mock
def test_interview_proxy_get():
    respx.get(f"{INTERVIEW_BASE}/api/auth/companies").mock(
        return_value=httpx.Response(200, json={"success": True, "data": []})
    )
    client = TestClient(app)
    response = client.get("/api/auth/companies")
    assert response.status_code == 200


@respx.mock
def test_interview_proxy_post():
    respx.post(f"{INTERVIEW_BASE}/api/auth/login").mock(
        return_value=httpx.Response(200, json={"success": True, "token": "abc"})
    )
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": "a@b.com", "password": "x"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Device Monitor API proxy (strips /device prefix)
# ---------------------------------------------------------------------------
@respx.mock
def test_device_proxy_strips_prefix():
    respx.get(f"{DEVICE_BASE}/api/candidates").mock(
        return_value=httpx.Response(200, json={"success": True, "data": []})
    )
    client = TestClient(app)
    response = client.get("/device/api/candidates")
    assert response.status_code == 200
    # Verify the mock was called (meaning /device prefix was stripped correctly)
    assert respx.calls.call_count == 1
    called_url = str(respx.calls[0].request.url)
    # URL should go to device-api host, NOT contain /device/api path
    assert "/device/api" not in called_url
    assert "/api/candidates" in called_url


@respx.mock
def test_device_proxy_nested_path():
    respx.get(f"{DEVICE_BASE}/api/candidates/123").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {}})
    )
    client = TestClient(app)
    response = client.get("/device/api/candidates/123")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Query parameters are preserved
# ---------------------------------------------------------------------------
@respx.mock
def test_query_params_preserved_interview():
    respx.get(f"{INTERVIEW_BASE}/api/interviews").mock(
        return_value=httpx.Response(200, json={"success": True, "data": []})
    )
    client = TestClient(app)
    response = client.get("/api/interviews?status=active&page=2")
    assert response.status_code == 200
    called_url = str(respx.calls[0].request.url)
    assert "status=active" in called_url
    assert "page=2" in called_url


@respx.mock
def test_query_params_preserved_device():
    respx.get(f"{DEVICE_BASE}/api/candidates").mock(
        return_value=httpx.Response(200, json={"success": True, "data": []})
    )
    client = TestClient(app)
    response = client.get("/device/api/candidates?status=online")
    assert response.status_code == 200
    called_url = str(respx.calls[0].request.url)
    assert "status=online" in called_url


# ---------------------------------------------------------------------------
# Authorization header is forwarded
# ---------------------------------------------------------------------------
@respx.mock
def test_authorization_header_forwarded():
    route = respx.get(f"{INTERVIEW_BASE}/api/interviews")
    route.mock(return_value=httpx.Response(200, json={"success": True, "data": []}))
    client = TestClient(app)
    client.get("/api/interviews", headers={"Authorization": "Bearer test-token"})
    forwarded = respx.calls[0].request.headers.get("authorization", "")
    assert forwarded == "Bearer test-token"


# ---------------------------------------------------------------------------
# JSON body is forwarded
# ---------------------------------------------------------------------------
@respx.mock
def test_json_body_forwarded():
    route = respx.post(f"{INTERVIEW_BASE}/api/auth/login")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    client = TestClient(app)
    client.post("/api/auth/login", json={"email": "test@example.com", "password": "secret"})
    import json
    body = json.loads(respx.calls[0].request.content)
    assert body["email"] == "test@example.com"


# ---------------------------------------------------------------------------
# Backend status codes pass through
# ---------------------------------------------------------------------------
@respx.mock
def test_backend_404_passthrough():
    respx.get(f"{INTERVIEW_BASE}/api/interviews/nonexistent").mock(
        return_value=httpx.Response(404, json={"success": False, "message": "Not found"})
    )
    client = TestClient(app)
    response = client.get("/api/interviews/nonexistent")
    assert response.status_code == 404


@respx.mock
def test_backend_401_passthrough():
    respx.get(f"{INTERVIEW_BASE}/api/interviews").mock(
        return_value=httpx.Response(401, json={"success": False, "message": "Unauthorized"})
    )
    client = TestClient(app)
    response = client.get("/api/interviews")
    assert response.status_code == 401


@respx.mock
def test_backend_500_passthrough():
    respx.get(f"{INTERVIEW_BASE}/api/interviews").mock(
        return_value=httpx.Response(500, json={"success": False, "message": "Server error"})
    )
    client = TestClient(app)
    response = client.get("/api/interviews")
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Unavailable backends return 502
# ---------------------------------------------------------------------------
@respx.mock
def test_interview_unavailable_502():
    respx.get(f"{INTERVIEW_BASE}/api/interviews").mock(side_effect=httpx.ConnectError("refused"))
    client = TestClient(app)
    response = client.get("/api/interviews")
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "BAD_GATEWAY"


@respx.mock
def test_device_unavailable_502():
    respx.get(f"{DEVICE_BASE}/api/candidates").mock(side_effect=httpx.ConnectError("refused"))
    client = TestClient(app)
    response = client.get("/device/api/candidates")
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "BAD_GATEWAY"


# ---------------------------------------------------------------------------
# Timeout returns 504
# ---------------------------------------------------------------------------
@respx.mock
def test_timeout_returns_504():
    respx.get(f"{INTERVIEW_BASE}/api/interviews").mock(side_effect=httpx.ReadTimeout("timeout"))
    client = TestClient(app)
    response = client.get("/api/interviews")
    assert response.status_code == 504
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "GATEWAY_TIMEOUT"
