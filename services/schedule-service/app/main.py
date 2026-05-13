"""schedule-service FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import nats as nats_module
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.database import engine
from app.models.base import Base
from app.routers import consignments, gantt, health, nagare, vendors
from app.services.event_consumer import start_event_consumer
from tms_shared.nats_client import get_nats_client, init_jetstream_streams

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# Global reference kept alive for the duration of the process
_nats_client: nats_module.NATS | None = None
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: start-up → serve → shut-down."""
    global _nats_client, _consumer_task

    # ── Database ──────────────────────────────────────────────────────
    logger.info("Ensuring database tables exist…")
    async with engine.begin() as conn:
        # In production, Alembic manages migrations.  This is a safety net
        # for development / first-run without migrations applied.
        await conn.run_sync(Base.metadata.create_all)

    # ── NATS ──────────────────────────────────────────────────────────
    try:
        logger.info("Connecting to NATS at %s…", settings.NATS_URL)
        _nats_client = await get_nats_client(settings.NATS_URL)
        js = _nats_client.jetstream()
        await init_jetstream_streams(js)

        # Start the background event consumer
        _consumer_task = asyncio.create_task(
            start_event_consumer(_nats_client),
            name="schedule-event-consumer",
        )
        logger.info("NATS event consumer started")
    except Exception as exc:  # noqa: BLE001
        logger.error("NATS connection failed (%s) — service starts without event subscription", exc)

    yield  # ← application is live

    # ── Shutdown ──────────────────────────────────────────────────────
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    if _nats_client:
        await _nats_client.close()
        logger.info("NATS connection closed")

    await engine.dispose()
    logger.info("Database engine disposed")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="TMS Schedule Service",
    description=(
        "Authoritative source for Nagare production schedules, consignments, "
        "Gantt chart data, and truck arrival validation for MSIL TMS."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/v1/schedule/docs",
    redoc_url="/api/v1/schedule/redoc",
    openapi_url="/api/v1/schedule/openapi.json",
)

# ── Prometheus metrics ────────────────────────────────────────────────────────
Instrumentator().instrument(app).expose(app, endpoint="/api/v1/schedule/metrics")

# ── Routers ───────────────────────────────────────────────────────────────────
PREFIX = "/api/v1/schedule"

app.include_router(health.router, prefix=PREFIX)
app.include_router(nagare.router, prefix=PREFIX)
app.include_router(consignments.router, prefix=PREFIX)
app.include_router(gantt.router, prefix=PREFIX)
app.include_router(vendors.router, prefix=PREFIX)
