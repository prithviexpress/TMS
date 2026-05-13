"""REST endpoints for truck management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.truck import Truck
from app.models.truck_movement import TruckMovement
from app.schemas.truck import TruckCreate, TruckResponse, TruckStatusPatch
from app.schemas.truck_movement import ManualEntryRequest, TruckMovementResponse

router = APIRouter(prefix="/api/v1/gate", tags=["trucks"])


@router.get("/trucks", response_model=list[TruckResponse])
async def list_trucks(
    db: Annotated[AsyncSession, Depends(get_db)],
    plate: str | None = Query(None, description="Filter by plate number (exact or partial)"),
    vendor_id: uuid.UUID | None = Query(None, description="Filter by vendor UUID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[TruckResponse]:
    """Return a paginated list of trucks, optionally filtered by plate or vendor.

    Args:
        db: Async DB session.
        plate: Optional plate substring filter (case-insensitive).
        vendor_id: Optional vendor UUID filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        List of :class:`TruckResponse`.
    """
    stmt = select(Truck)
    if plate:
        stmt = stmt.where(Truck.plate_number.ilike(f"%{plate}%"))
    if vendor_id:
        stmt = stmt.where(Truck.vendor_id == vendor_id)
    stmt = stmt.order_by(Truck.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    trucks = result.scalars().all()
    return [TruckResponse.model_validate(t) for t in trucks]


@router.get("/trucks/{plate}", response_model=TruckResponse)
async def get_truck_by_plate(
    plate: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TruckResponse:
    """Return a single truck record by exact plate number.

    Args:
        plate: Licence plate number (exact match, case-sensitive).
        db: Async DB session.

    Raises:
        HTTPException 404: If no truck with that plate is found.

    Returns:
        :class:`TruckResponse`.
    """
    result = await db.execute(select(Truck).where(Truck.plate_number == plate))
    truck = result.scalars().first()
    if truck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    return TruckResponse.model_validate(truck)


@router.post("/trucks", response_model=TruckMovementResponse, status_code=status.HTTP_201_CREATED)
async def manual_entry(
    payload: ManualEntryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TruckMovementResponse:
    """Admin fallback: manually register a truck arrival when ALPR has failed.

    Creates or updates a :class:`Truck` record and creates a new
    :class:`TruckMovement` in ``proceeding`` status.

    Args:
        payload: Manual entry details.
        db: Async DB session.

    Returns:
        The newly created :class:`TruckMovementResponse`.
    """
    # Upsert Truck
    result = await db.execute(select(Truck).where(Truck.plate_number == payload.plate_number))
    truck = result.scalars().first()

    now = datetime.now(timezone.utc)

    if truck is None:
        truck = Truck(
            plate_number=payload.plate_number,
            vendor_id=payload.vendor_id,
            driver_name=payload.driver_name,
            driver_phone=payload.driver_phone,
        )
        db.add(truck)
        await db.flush()
    else:
        if payload.vendor_id is not None:
            truck.vendor_id = payload.vendor_id
        if payload.driver_name is not None:
            truck.driver_name = payload.driver_name
        if payload.driver_phone is not None:
            truck.driver_phone = payload.driver_phone
        await db.flush()

    movement = TruckMovement(
        truck_id=truck.id,
        consignment_id=payload.consignment_id,
        plate_number=payload.plate_number,
        status="proceeding",
        gate_in_at=now,
        bay_code=payload.bay_code,
    )
    db.add(movement)
    await db.flush()

    return TruckMovementResponse.model_validate(movement)


@router.patch("/trucks/{plate}/status", response_model=TruckMovementResponse)
async def override_truck_status(
    plate: str,
    payload: TruckStatusPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TruckMovementResponse:
    """Override the status of the most recent active truck movement for a plate.

    Intended for operator manual corrections (e.g. allow a held truck through,
    or reject one that slipped past automated checks).

    Args:
        plate: Licence plate number.
        payload: New status and optional rejection reason.
        db: Async DB session.

    Raises:
        HTTPException 404: If no active movement is found for this plate.
        HTTPException 422: If the requested status is not valid.

    Returns:
        Updated :class:`TruckMovementResponse`.
    """
    from app.models.truck_movement import MOVEMENT_STATUSES

    if payload.status not in MOVEMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{payload.status}'. Must be one of: {', '.join(MOVEMENT_STATUSES)}",
        )

    result = await db.execute(
        select(TruckMovement)
        .where(
            TruckMovement.plate_number == plate,
            TruckMovement.status.notin_(["departed", "rejected"]),
        )
        .order_by(TruckMovement.created_at.desc())
        .limit(1)
    )
    movement = result.scalars().first()

    if movement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active truck movement found for plate {plate!r}",
        )

    movement.status = payload.status
    if payload.rejection_reason is not None:
        movement.rejection_reason = payload.rejection_reason
    movement.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return TruckMovementResponse.model_validate(movement)
