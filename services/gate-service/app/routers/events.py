"""REST endpoints for gate events and truck movement log."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.gate_event import GateEvent
from app.models.truck_movement import TruckMovement
from app.schemas.gate_event import GateEventResponse
from app.schemas.truck_movement import TruckMovementResponse

router = APIRouter(prefix="/api/v1/gate", tags=["events"])


@router.get("/health")
async def health_check() -> dict:
    """Liveness probe.

    Returns:
        ``{"status": "ok"}``
    """
    return {"status": "ok"}


@router.get("/events", response_model=list[GateEventResponse])
async def list_gate_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    plate: str | None = Query(None, description="Filter by plate number (partial, case-insensitive)"),
    camera_id: str | None = Query(None, description="Filter by camera_id"),
    direction: str | None = Query(None, description="Filter by direction: 'entry' or 'exit'"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[GateEventResponse]:
    """Return a paginated log of all raw gate (ALPR) events.

    Args:
        db: Async DB session.
        plate: Optional plate substring filter.
        camera_id: Optional camera ID filter (e.g. ``"gate_2"``).
        direction: Optional direction filter (``"entry"`` | ``"exit"``).
        limit: Page size.
        offset: Page offset.

    Returns:
        List of :class:`GateEventResponse`.
    """
    stmt = select(GateEvent)
    if plate:
        stmt = stmt.where(GateEvent.plate_number.ilike(f"%{plate}%"))
    if camera_id:
        stmt = stmt.where(GateEvent.camera_id == camera_id)
    if direction:
        stmt = stmt.where(GateEvent.direction == direction)

    stmt = stmt.order_by(GateEvent.detected_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    events = result.scalars().all()
    return [GateEventResponse.model_validate(e) for e in events]


@router.get("/movements", response_model=list[TruckMovementResponse])
async def list_truck_movements(
    db: Annotated[AsyncSession, Depends(get_db)],
    plate: str | None = Query(None, description="Filter by plate number (partial)"),
    status: str | None = Query(None, description="Filter by status"),
    vendor_id: uuid.UUID | None = Query(None, description="Filter by vendor UUID"),
    consignment_id: uuid.UUID | None = Query(None, description="Filter by consignment UUID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[TruckMovementResponse]:
    """Return a paginated list of all truck movements.

    Args:
        db: Async DB session.
        plate: Optional plate substring filter.
        status: Optional status filter (e.g. ``"proceeding"``).
        vendor_id: Optional vendor UUID filter.
        consignment_id: Optional consignment UUID filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        List of :class:`TruckMovementResponse`.
    """
    stmt = select(TruckMovement)

    if plate:
        stmt = stmt.where(TruckMovement.plate_number.ilike(f"%{plate}%"))
    if status:
        stmt = stmt.where(TruckMovement.status == status)
    if consignment_id:
        stmt = stmt.where(TruckMovement.consignment_id == consignment_id)

    # vendor_id requires joining through Truck
    if vendor_id:
        from app.models.truck import Truck

        stmt = stmt.join(Truck, TruckMovement.truck_id == Truck.id, isouter=True).where(
            Truck.vendor_id == vendor_id
        )

    stmt = stmt.order_by(TruckMovement.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    movements = result.scalars().all()
    return [TruckMovementResponse.model_validate(m) for m in movements]
