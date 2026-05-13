"""FastAPI application entry-point for vendor-service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
import nats
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.database import engine
from app.models.vendor import Base
from app.routers.vendors import router as vendors_router
from tms_shared.nats_client import get_nats_client, init_jetstream_streams

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect NATS, create DB tables, init httpx client.
    Shutdown: close all connections gracefully.
    """
    logger.info("vendor-service starting up")

    # ── Database ───────────────────────────────────────────────────────────────
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── NATS ───────────────────────────────────────────────────────────────────
    nc: nats.NATS = await get_nats_client(settings.NATS_URL)
    js = nc.jetstream()
    await init_jetstream_streams(js)
    app.state.nats_client = nc
    app.state.nats_js = js

    # ── HTTP client (shared, keep-alive) ───────────────────────────────────────
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    app.state.http_client = http_client

    logger.info("vendor-service ready")
    yield

    # ── Teardown ───────────────────────────────────────────────────────────────
    logger.info("vendor-service shutting down")
    await http_client.aclose()
    await nc.drain()
    await engine.dispose()


app = FastAPI(
    title="TMS Vendor Service",
    version="0.1.0",
    description=(
        "Vendor master management and self-service truck registration "
        "for the Truck Movement System."
    ),
    lifespan=lifespan,
    docs_url="/api/v1/vendors/docs",
    redoc_url="/api/v1/vendors/redoc",
    openapi_url="/api/v1/vendors/openapi.json",
)

# Prometheus metrics at /metrics
Instrumentator().instrument(app).expose(app)

app.include_router(vendors_router)
