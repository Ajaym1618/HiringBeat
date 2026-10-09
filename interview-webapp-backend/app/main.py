import socketio
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.socket_events import sio
from app.routes import auth, interviews, monitoring, detection, media, device, face_verify, admin, company, org, candidates


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="InterBeat Interview API",
    description="Core backend for the InterBeat remote proctoring platform — handles auth, interviews, AI detection, WebRTC signaling, device bridge, face verification, and admin.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Error response helper ─────────────────────────────────────────────────────
def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message,
            "error": {
                "code": code,
            },
        },
    )


# ── Validation errors (422) ───────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        field = next((str(loc) for loc in reversed(error["loc"]) if loc != "body"), "unknown")
        error_type = error.get("type", "")
        if error_type == "missing":
            messages.append(f"{field.replace('_', ' ').capitalize()} is required")
        elif error_type == "literal_error":
            messages.append(f"Invalid {field.replace('_', ' ')}")
        else:
            messages.append(error["msg"].replace("Value error, ", ""))
    return error_response(422, "VALIDATION_ERROR", " | ".join(messages))


# ── HTTP exceptions (401, 403, 404, etc.) ────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        500: "INTERNAL_SERVER_ERROR",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, exc.detail)


# ── Rate limit exceeded (429) ─────────────────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return error_response(429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please slow down.")


# ── Unhandled exceptions (500) ────────────────────────────────────────────────
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return error_response(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")


# ── Rate limiter state ────────────────────────────────────────────────────────
app.state.limiter = limiter

# ── CORS ──────────────────────────────────────────────────────────────────────
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(interviews.router)
app.include_router(monitoring.router)
app.include_router(detection.router)
app.include_router(media.router)
app.include_router(device.router)
app.include_router(face_verify.router)
app.include_router(admin.router)
app.include_router(company.router)
app.include_router(org.router)
app.include_router(candidates.router)

# ── Socket.IO ─────────────────────────────────────────────────────────────────
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
