"""Bay-service FastAPI application entry point.

Startup sequence (lifespan):
1. Connect to NATS and initialise JetStream streams.
2. Initialise Redis connection pool.
3. Start NATS event consumer (tms.gate.truck_arrived).
4. Create DB tables (dev/test only — production uses Alembic).

Shutdown sequence:
1. Close NATS connection.
2. Close Redis pool.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.cache import close_redis_pool, init_redis_pool
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.routers import bays as bays_router
from app.routers import sensor as sensor_router
from tms_shared.nats_client import get_nats_client, init_jetstream_streams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of external connections."""
    # ── NATS ──────────────────────────────────────────────────────────────────
    logger.info("Connecting to NATS at %s", settings.NATS_URL)
    nc = await get_nats_client(settings.NATS_URL)
    js = nc.jetstream()
    await init_jetstream_streams(js)
    app.state.nats_client = nc
    logger.info("NATS connected and streams initialised")

    # ── Redis ─────────────────────────────────────────────────────────────────
    logger.info("Initialising Redis pool at %s", settings.REDIS_URL)
    redis_pool = init_redis_pool()
    app.state.redis = redis_pool
    logger.info("Redis pool ready")

    # ── NATS event consumer ───────────────────────────────────────────────────
    try:
        from app.services.event_consumer import start_event_consumer
        await start_event_consumer(nc, redis_pool, AsyncSessionLocal)
        logger.info("NATS event consumer started")
    except Exception as exc:  # noqa: BLE001
        logger.error("NATS consumer startup error (non-fatal): %s", exc)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down bay-service …")
    await nc.drain()
    await close_redis_pool()
    await engine.dispose()
    logger.info("bay-service shut down cleanly")


def create_app() -> FastAPI:
    application = FastAPI(
        title="TMS Bay Service",
        description=(
            "Manages 160 dock bays: LoRaWAN sensor ingestion, occupancy state machine, "
            "Redis caching, SSE live dashboard, and K70 light control."
        ),
        version="1.0.0",
        docs_url="/api/v1/bays/docs",
        redoc_url="/api/v1/bays/redoc",
        openapi_url="/api/v1/bays/openapi.json",
        lifespan=lifespan,
    )

    # Routers
    application.include_router(bays_router.router)
    application.include_router(sensor_router.router)

    # Prometheus metrics
    Instrumentator().instrument(application).expose(
        application, endpoint="/api/v1/bays/metrics"
    )

    return application


app = create_app()
