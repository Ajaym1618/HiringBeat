import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db
from app.socket_events import sio
from app.routes import report, candidates


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="InterBeat Device Monitor API",
    description="Device telemetry backend for the InterBeat remote proctoring platform — receives candidate device reports (USB, Wi-Fi, apps) and streams live updates to the recruiter dashboard.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report.router)
app.include_router(candidates.router)

# Mount Socket.IO
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
