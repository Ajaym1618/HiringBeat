import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# App — defined after lifespan (below)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Hop-by-hop headers that must NOT be forwarded
# ---------------------------------------------------------------------------
_HOP_BY_HOP = frozenset([
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",  # always rebuild from target URL
])

# Headers that should NOT be logged (sensitive)
_SENSITIVE_HEADERS = frozenset(["authorization", "cookie", "set-cookie", "x-bridge-key", "x-dashboard-key"])


def _filter_request_headers(headers: dict) -> dict:
    """Remove hop-by-hop headers; keep all others (including auth headers for forwarding)."""
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP
    }


def _filter_response_headers(headers) -> dict:
    """Remove hop-by-hop and content-encoding headers that httpx already decoded."""
    skip = _HOP_BY_HOP | {"content-encoding", "content-length"}
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in skip
    }


def _log_safe_headers(headers: dict) -> dict:
    """Return headers dict with sensitive values redacted — for logging only."""
    return {
        k: "[REDACTED]" if k.lower() in _SENSITIVE_HEADERS else v
        for k, v in headers.items()
    }


# ---------------------------------------------------------------------------
# Shared async HTTP client — lazy init so tests work without lifespan
# ---------------------------------------------------------------------------
_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Return the shared client, creating it lazily if needed."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.PROXY_TIMEOUT),
            follow_redirects=False,
        )
    return _client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.PROXY_TIMEOUT),
        follow_redirects=False,
    )
    logger.info("Gateway started — Interview API: %s | Device Monitor API: %s",
                settings.INTERVIEW_API_URL, settings.DEVICE_MONITOR_API_URL)
    yield
    if _client:
        await _client.aclose()
    logger.info("Gateway shut down.")


# ---------------------------------------------------------------------------
# App — defined here so lifespan is already in scope
# ---------------------------------------------------------------------------
app = FastAPI(
    title="InterBeat Gateway",
    description="Reverse-proxy gateway for InterBeat — routes /api/* to the Interview API and /device/api/* to the Device Monitor API.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
_cors_origins_raw = settings.GATEWAY_CORS_ORIGINS.strip()
cors_origins: list = ["*"] if _cors_origins_raw == "*" else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error response helper (matches existing service format)
# ---------------------------------------------------------------------------
def _error_json(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "message": message,
            "error": {"code": code},
        },
    )


# ---------------------------------------------------------------------------
# Core proxy helper
# ---------------------------------------------------------------------------
async def _proxy_request(request: Request, target_url: str, service_name: str) -> StreamingResponse | JSONResponse:
    """Forward an incoming HTTP request to target_url and stream back the response."""
    client = get_client()
    start = time.monotonic()

    # Build outgoing headers
    forwarded_headers = _filter_request_headers(dict(request.headers))

    # Build target URL with query string
    params = dict(request.query_params)

    try:
        backend_response = await client.request(
            method=request.method,
            url=target_url,
            headers=forwarded_headers,
            content=await request.body(),
            params=params,
        )
    except httpx.ConnectError:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("%s %s -> %s [502] %dms — connection refused",
                     request.method, request.url.path, service_name, duration_ms)
        return _error_json(502, "BAD_GATEWAY", f"{service_name} unavailable")
    except httpx.TimeoutException:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("%s %s -> %s [504] %dms — timeout",
                     request.method, request.url.path, service_name, duration_ms)
        return _error_json(504, "GATEWAY_TIMEOUT", "Request timed out")
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("%s %s -> %s [502] %dms — unexpected error: %s",
                     request.method, request.url.path, service_name, duration_ms, type(exc).__name__)
        return _error_json(502, "BAD_GATEWAY", f"{service_name} unavailable")

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("%s %s -> %s [%d] %dms",
                request.method, request.url.path, service_name,
                backend_response.status_code, duration_ms)

    response_headers = _filter_response_headers(dict(backend_response.headers))

    return StreamingResponse(
        content=backend_response.aiter_bytes(),
        status_code=backend_response.status_code,
        headers=response_headers,
        media_type=backend_response.headers.get("content-type"),
    )


# ---------------------------------------------------------------------------
# WebSocket proxy helper
# ---------------------------------------------------------------------------
async def _proxy_websocket(client_ws: WebSocket, target_ws_url: str, service_name: str) -> None:
    """
    Bidirectional WebSocket proxy using the `websockets` library.

    Note: python-socketio uses ASGI mode in both backend services, which means
    Socket.IO connections come in as WebSocket upgrades. This function bridges
    the raw WebSocket frames between the client and the backend Socket.IO server.
    The HTTP long-polling transport of Socket.IO also works through the HTTP proxy
    routes above (/api/* and /device/api/*).
    """
    await client_ws.accept()
    logger.info("WS connect -> %s (%s)", target_ws_url, service_name)

    try:
        async with websockets.connect(
            target_ws_url,
            additional_headers={
                k: v
                for k, v in client_ws.headers.items()
                if k.lower() not in _HOP_BY_HOP
            },
            open_timeout=settings.PROXY_TIMEOUT,
            close_timeout=10,
        ) as backend_ws:

            async def client_to_backend():
                try:
                    while True:
                        data = await client_ws.receive_bytes()
                        await backend_ws.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception:  # noqa: BLE001
                    pass

            async def backend_to_client():
                try:
                    async for message in backend_ws:
                        if isinstance(message, bytes):
                            await client_ws.send_bytes(message)
                        else:
                            await client_ws.send_text(message)
                except Exception:  # noqa: BLE001
                    pass

            await asyncio.gather(client_to_backend(), backend_to_client())

    except (OSError, websockets.exceptions.WebSocketException) as exc:
        logger.error("WS proxy error -> %s: %s", service_name, exc)
        try:
            await client_ws.close(code=1014)  # 1014 = Bad Gateway
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.error("WS proxy unexpected error -> %s: %s", service_name, type(exc).__name__)
        try:
            await client_ws.close()
        except Exception:  # noqa: BLE001
            pass

    logger.info("WS disconnect -> %s (%s)", target_ws_url, service_name)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", include_in_schema=True)
async def health_check():
    """Simple liveness check — no auth required."""
    return {"status": "ok", "service": "gateway"}


# ---------------------------------------------------------------------------
# Interview API HTTP proxy   /api/{path} -> INTERVIEW_API_URL/api/{path}
# ---------------------------------------------------------------------------
@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def interview_proxy(path: str, request: Request):
    target = f"{settings.INTERVIEW_API_URL}/api/{path}"
    return await _proxy_request(request, target, "Interview API")


# ---------------------------------------------------------------------------
# Device Monitor API HTTP proxy   /device/api/{path} -> DEVICE_MONITOR_API_URL/api/{path}
# NOTE: /device prefix is stripped — only /api/{path} is forwarded.
# ---------------------------------------------------------------------------
@app.api_route(
    "/device/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def device_proxy(path: str, request: Request):
    target = f"{settings.DEVICE_MONITOR_API_URL}/api/{path}"
    return await _proxy_request(request, target, "Device Monitor API")


# ---------------------------------------------------------------------------
# Interview Socket.IO WebSocket proxy   /socket.io/{path} -> INTERVIEW_API_URL
# ---------------------------------------------------------------------------
@app.websocket("/socket.io/{path:path}")
async def interview_ws_proxy(websocket: WebSocket, path: str):
    qs = websocket.url.query
    target_url = f"{settings.INTERVIEW_API_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/socket.io/{path}"
    if qs:
        target_url = f"{target_url}?{qs}"
    await _proxy_websocket(websocket, target_url, "Interview API")


# ---------------------------------------------------------------------------
# Device Monitor Socket.IO WebSocket proxy   /device/socket.io/{path} -> DEVICE_MONITOR_API_URL
# ---------------------------------------------------------------------------
@app.websocket("/device/socket.io/{path:path}")
async def device_ws_proxy(websocket: WebSocket, path: str):
    qs = websocket.url.query
    target_url = f"{settings.DEVICE_MONITOR_API_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/socket.io/{path}"
    if qs:
        target_url = f"{target_url}?{qs}"
    await _proxy_websocket(websocket, target_url, "Device Monitor API")
