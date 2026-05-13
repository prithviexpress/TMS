"""Gate-service FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import boto3
import httpx
import nats
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from tms_shared.nats_client import get_nats_client, init_jetstream_streams

from app.config import get_settings
from app.database import engine
from app.models.base import Base
from app.routers import events as events_router
from app.routers import trucks as trucks_router
from app.services.alpr_consumer import start_alpr_consumer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (populated during lifespan)
# ---------------------------------------------------------------------------
_nats_client: nats.NATS | None = None
_http_client: httpx.AsyncClient | None = None
_minio_client = None
_consumer_task: asyncio.Task | None = None


def _build_minio_client(settings):
    """Construct a boto3 S3 client pointing at the MinIO endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=f"http://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup → yield → shutdown."""
    global _nats_client, _http_client, _minio_client, _consumer_task

    settings = get_settings()

    # ── Database: create tables if not present (dev convenience) ──────────────
    # In production, tables are managed by Alembic migrations. The create_all
    # call here is a safety net so the service can start without running
    # migrations first (useful in CI / local dev).
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified / created")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialise database tables: %s", exc)
        raise

    # ── NATS ──────────────────────────────────────────────────────────────────
    try:
        _nats_client = await get_nats_client(settings.NATS_URL)
        js = _nats_client.jetstream()
        await init_jetstream_streams(js)
        logger.info("NATS connected and streams initialised")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to connect to NATS: %s", exc)
        raise

    # ── HTTP client (shared, connection-pooled) ────────────────────────────────
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )

    # ── MinIO client ──────────────────────────────────────────────────────────
    try:
        _minio_client = _build_minio_client(settings)
        logger.info("MinIO client initialised for endpoint %s", settings.MINIO_ENDPOINT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO client initialisation failed (non-fatal): %s", exc)
        _minio_client = None

    # ── ALPR Consumer ─────────────────────────────────────────────────────────
    try:
        _consumer_task = await start_alpr_consumer(
            nc=_nats_client,
            schedule_service_url=settings.SCHEDULE_SERVICE_URL,
            http_client=_http_client,
            minio_client=_minio_client,
        )
        logger.info("ALPR consumer started")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start ALPR consumer: %s", exc)
        raise

    # ── Store references on app.state for dependency injection in tests ────────
    app.state.nats_client = _nats_client
    app.state.http_client = _http_client
    app.state.minio_client = _minio_client

    yield  # ← application is running

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Gate-service shutting down…")

    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    if _http_client:
        await _http_client.aclose()

    if _nats_client and _nats_client.is_connected:
        await _nats_client.drain()
        await _nats_client.close()

    await engine.dispose()
    logger.info("Gate-service shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TMS Gate Service",
    description=(
        "Entry point for all truck movements at MSIL. "
        "Processes ALPR camera events, applies Nagare window logic, "
        "and publishes gate events to NATS JetStream."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── Prometheus metrics ────────────────────────────────────────────────────────
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(trucks_router.router)
app.include_router(events_router.router)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
