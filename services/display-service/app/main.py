"""Display-service FastAPI application entry point.

Lifecycle:
  1. Async SQLAlchemy engine + tables created (``CREATE TABLE IF NOT EXISTS``).
  2. Shared httpx client opened.
  3. NATS connection established and JetStream streams initialised.
  4. Event consumer subscriptions registered.
  5. Prometheus metrics instrumented.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.database import engine
from app.models.led_display import Base as LEDBase
from app.models.k70_state import K70LightState  # noqa: F401 — ensure model registered
from app.routers import led, lights
from app.services.event_consumer import start_event_consumer
from tms_shared.nats_client import get_nats_client, init_jetstream_streams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle manager."""
    settings = get_settings()

    # ── DB: create tables ─────────────────────────────────────────────────────
    async with engine.begin() as conn:
        await conn.run_sync(LEDBase.metadata.create_all)
    logger.info("Database tables ensured")

    # ── HTTP client ───────────────────────────────────────────────────────────
    http_client = httpx.AsyncClient()
    app.state.http_client = http_client

    # ── NATS ──────────────────────────────────────────────────────────────────
    nc = await get_nats_client(settings.NATS_URL)
    js = nc.jetstream()
    await init_jetstream_streams(js)
    app.state.nats = nc

    # ── Event consumers ───────────────────────────────────────────────────────
    await start_event_consumer(nc, http_client)

    logger.info("Display-service started on port 8006")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await nc.drain()
    await http_client.aclose()
    await engine.dispose()
    logger.info("Display-service shut down cleanly")


app = FastAPI(
    title="TMS Display Service",
    description="Controls LED display panels and Banner K70 bay lights",
    version="0.1.0",
    lifespan=lifespan,
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Routers
app.include_router(led.router)
app.include_router(lights.router)
