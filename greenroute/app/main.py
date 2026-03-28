"""
main.py — GreenRoute Intelligence Platform FastAPI application.

Start the server:
    uv run uvicorn app.main:app --reload --port 8000

Endpoints:
    GET  /health
    POST /corridor/run
    GET  /corridor/status/{corridor_id}
    GET  /docs          (Swagger UI)
    GET  /redoc         (ReDoc)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import corridor, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    logger.info("GreenRoute API starting up …")
    # Eagerly import the graph so LangGraph compilation errors surface at boot,
    # not on the first request.
    from app.agent.graph import graph  # noqa: F401
    logger.info("LangGraph compiled successfully.")
    yield
    logger.info("GreenRoute API shutting down.")


app = FastAPI(
    title="GreenRoute Intelligence Platform",
    description=(
        "Multi-agent carbon certification for shipping and aviation corridors. "
        "Satellite data → A* green routing → certification."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Permissive for development; tighten allow_origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(corridor.router)
