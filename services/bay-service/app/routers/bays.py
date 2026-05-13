"""Bay management endpoints.

Routes
------
GET    /api/v1/bays                   — list all bays (Redis cache → DB fallback)
GET    /api/v1/bays/health            — liveness probe
GET    /api/v1/bays/events/stream     — SSE live dashboard stream
GET    /api/v1/bays/{bay_id}          — single bay detail
PATCH  /api/v1/bays/{bay_id}/assign   — assign truck movement to bay
PATCH  /api/v1/bays/{bay_id}/release  — mark bay VACANT
GET    /api/v1/bays/{bay_id}/history  — occupancy history for Gantt chart
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_all_bay_statuses, get_bay_status, get_redis, set_bay_status
from app.config import settings
from app.database import get_db
from app.models.bay import Bay
from app.models.bay_occupancy import BayOccupancy
from app.models.bay_occupancy_history import BayOccupancyHistory
from app.schemas.bay import (
    BayAssignRequest,
    BayOccupancyHistoryResponse,
    BayReleaseRequest,
    BayResponse,
    BayStatusResponse,
)
from app.services.occupancy import assign_bay, release_bay
from tms_shared.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bays", tags=["bays"])

# ---------------------------------------------------------------------------
# SSE event bus — one asyncio.Queue per connected client
# ---------------------------------------------------------------------------
_sse_subscribers: list[asyncio.Queue] = []


def get_sse_subscribers() -> list[asyncio.Queue]:
    return _sse_subscribers


async def broadcast_bay_event(event: dict) -> None:
    """Push *event* to every connected SSE subscriber queue."""
    dead: list[asyncio.Queue] = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _sse_subscribers.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Helper: get bay or 404
# ---------------------------------------------------------------------------

async def _get_bay(bay_id: UUID, db: AsyncSession) -> Bay:
    result = await db.execute(select(Bay).where(Bay.id == bay_id))
    bay = result.scalar_one_or_none()
    if bay is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bay not found")
    return bay


async def _get_bay_response(bay: Bay, db: AsyncSession) -> BayResponse:
    """Build a BayResponse, fetching the embedded occupancy record."""
    result = await db.execute(
        select(BayOccupancy).where(BayOccupancy.bay_id == bay.id)
    )
    occ = result.scalar_one_or_none()

    resp = BayResponse.model_validate(bay)
    if occ:
        from app.schemas.bay import BayOccupancyEmbed
        resp.current_occupancy = BayOccupancyEmbed.model_validate(occ)
    return resp


# ---------------------------------------------------------------------------
# Routes (static paths first to avoid ambiguity)
# ---------------------------------------------------------------------------


@router.get("/health")
async def health_check():
    """Liveness probe used by docker-compose and load balancer."""
    return {"status": "ok"}


@router.get("/events/stream")
async def sse_stream(request: Request):
    """Server-Sent Events stream — pushes bay state changes to Mendix.

    Each event is a JSON object:
        data: {"bay_code": "AR-N1", "status": "OCCUPIED", ...}\\n\\n

    Clients reconnect automatically; no authentication is required for SSE
    because Mendix widget does not support Bearer on EventSource.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_subscribers.append(queue)

    async def _event_generator():
        try:
            # Send a comment immediately to confirm the connection
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    payload = json.dumps(event, default=str)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Send a heartbeat comment to keep the connection alive
                    yield ": heartbeat\n\n"
        finally:
            try:
                _sse_subscribers.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[BayStatusResponse])
async def list_bays(
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_db)],
    zone: str | None = Query(None, description="Filter by zone (e.g. AR, ARC, C)"),
    status_filter: str | None = Query(None, alias="status", description="VACANT|OCCUPIED|RESERVED"),
):
    """Return all bay statuses.

    Attempts to serve the full list from Redis.  Falls back to a DB query when
    the cache is cold or partially populated.
    """
    cached = await get_all_bay_statuses(redis)

    if cached:
        results = cached
    else:
        # DB fallback — join bays + bay_occupancy
        rows = await db.execute(
            select(Bay, BayOccupancy)
            .outerjoin(BayOccupancy, BayOccupancy.bay_id == Bay.id)
            .where(Bay.is_active.is_(True))
            .order_by(Bay.bay_code)
        )
        results = []
        for bay, occ in rows.all():
            now = datetime.now(timezone.utc)
            time_left = None
            if occ and occ.expected_release_at:
                delta = occ.expected_release_at - now
                time_left = max(0, int(delta.total_seconds() / 60))
            entry = {
                "bay_code": bay.bay_code,
                "zone": bay.zone,
                "status": occ.status if occ else "VACANT",
                "vendor_name": occ.vendor_name if occ else None,
                "truck_plate": occ.truck_plate if occ else None,
                "occupied_at": occ.occupied_at.isoformat() if occ and occ.occupied_at else None,
                "time_left_minutes": time_left,
            }
            results.append(entry)
            # Warm the cache while we're here
            if occ:
                await set_bay_status(redis, bay.bay_code, entry)

    # Apply optional filters
    if zone:
        results = [r for r in results if r.get("zone") == zone]
    if status_filter:
        results = [r for r in results if r.get("status") == status_filter.upper()]

    return [BayStatusResponse(**r) for r in results]


@router.get("/{bay_id}", response_model=BayResponse)
async def get_bay(
    bay_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _token: Annotated[dict, Depends(verify_token)],
):
    """Return full detail for a single bay including current occupancy."""
    bay = await _get_bay(bay_id, db)
    return await _get_bay_response(bay, db)


@router.patch("/{bay_id}/assign", response_model=BayResponse)
async def assign_bay_endpoint(
    bay_id: UUID,
    body: BayAssignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    request: Request,
    _token: Annotated[dict, Depends(verify_token)],
):
    """Assign a truck movement to a bay (transitions to RESERVED or OCCUPIED)."""
    bay = await _get_bay(bay_id, db)

    nc = request.app.state.nats_client
    await assign_bay(
        db=db,
        redis=redis,
        nc=nc,
        bay=bay,
        movement_id=body.movement_id,
        vendor_id=body.vendor_id,
        vendor_name=body.vendor_name,
        truck_plate=body.truck_plate,
        expected_release_at=body.expected_release_at,
        display_service_url=settings.DISPLAY_SERVICE_URL,
        status="RESERVED",
    )

    # Broadcast to SSE subscribers
    cached = await get_bay_status(redis, bay.bay_code)
    if cached:
        await broadcast_bay_event(cached)

    return await _get_bay_response(bay, db)


@router.patch("/{bay_id}/release", response_model=BayResponse)
async def release_bay_endpoint(
    bay_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    request: Request,
    body: BayReleaseRequest | None = None,
    _token: Annotated[dict, Depends(verify_token)] = None,
):
    """Release a bay back to VACANT."""
    bay = await _get_bay(bay_id, db)

    nc = request.app.state.nats_client
    await release_bay(
        db=db,
        redis=redis,
        nc=nc,
        bay=bay,
        display_service_url=settings.DISPLAY_SERVICE_URL,
    )

    cached = await get_bay_status(redis, bay.bay_code)
    if cached:
        await broadcast_bay_event(cached)

    return await _get_bay_response(bay, db)


@router.get("/{bay_id}/history", response_model=list[BayOccupancyHistoryResponse])
async def get_bay_history(
    bay_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _token: Annotated[dict, Depends(verify_token)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return paginated occupancy history for a bay (for Gantt chart)."""
    bay = await _get_bay(bay_id, db)
    result = await db.execute(
        select(BayOccupancyHistory)
        .where(BayOccupancyHistory.bay_id == bay.id)
        .order_by(BayOccupancyHistory.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [BayOccupancyHistoryResponse.model_validate(r) for r in rows]
