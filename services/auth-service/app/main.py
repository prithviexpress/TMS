"""FastAPI application entry-point for auth-service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.database import engine
from app.models.user import Base
from app.routers.auth import router as auth_router

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup (idempotent; Alembic handles migrations)."""
    logger.info("auth-service starting up")
    async with engine.begin() as conn:
        # create_all is a no-op when tables already exist; in production
        # Alembic migrations are the authoritative schema manager.
        await conn.run_sync(Base.metadata.create_all)
    logger.info("auth-service ready")
    yield
    logger.info("auth-service shutting down")
    await engine.dispose()


app = FastAPI(
    title="TMS Auth Service",
    version="0.1.0",
    description="Authentication and user management for the Truck Movement System.",
    lifespan=lifespan,
    docs_url="/api/v1/auth/docs",
    redoc_url="/api/v1/auth/redoc",
    openapi_url="/api/v1/auth/openapi.json",
)

# Prometheus metrics at /metrics
Instrumentator().instrument(app).expose(app)

app.include_router(auth_router)
