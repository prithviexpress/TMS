"""Consignment routes.

Endpoints
---------
GET    /api/v1/schedule/consignments              — list with filters
POST   /api/v1/schedule/consignments              — create
GET    /api/v1/schedule/consignments/check/{plate} — gate check
GET    /api/v1/schedule/consignments/{id}          — get one
PATCH  /api/v1/schedule/consignments/{id}          — update
POST   /api/v1/schedule/consignments/{id}/assign-bay
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.consignment import Consignment
from app.models.vendor import Vendor
from app.schemas.consignment import (
    ConsignmentCreate,
    ConsignmentForGateCheck,
    ConsignmentResponse,
    ConsignmentUpdate,
)

router = APIRouter(tags=["consignments"])

_ACTIVE_STATUSES = [
    "SCHEDULED",
    "TRUCK_REGISTERED",
    "TRUCK_AT_GATE",
    "TRUCK_PROCEEDING",
    "TRUCK_AT_BAY",
]


@router.get("/consignments", response_model=list[ConsignmentResponse])
async def list_consignments(
    date: date | None = Query(None, description="Filter by slot_start date (YYYY-MM-DD)"),
    vendor_id: uuid.UUID | None = Query(None),
    bay_code: str | None = Query(None),
    status: str | None = Query(None, description="Filter by status string"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ConsignmentResponse]:
    """List consignments with optional filters."""
    filters = []
    if date:
        day_start = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(date.year, date.month, date.day, 23, 59, 59, tzinfo=timezone.utc)
        filters.append(Consignment.slot_start >= day_start)
        filters.append(Consignment.slot_start <= day_end)
    if vendor_id:
        filters.append(Consignment.vendor_id == vendor_id)
    if bay_code:
        filters.append(Consignment.bay_code == bay_code)
    if status:
        filters.append(Consignment.status == status)

    stmt = (
        select(Consignment)
        .where(and_(*filters) if filters else True)
        .order_by(Consignment.slot_start)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/consignments", response_model=ConsignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_consignment(
    payload: ConsignmentCreate,
    db: AsyncSession = Depends(get_db),
) -> ConsignmentResponse:
    """Create a single consignment."""
    # Verify vendor exists
    vendor_result = await db.execute(select(Vendor).where(Vendor.id == payload.vendor_id))
    if vendor_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {payload.vendor_id} not found",
        )

    consignment = Consignment(**payload.model_dump())
    db.add(consignment)
    await db.flush()
    await db.refresh(consignment)
    return consignment


@router.get("/consignments/check/{plate}", response_model=ConsignmentForGateCheck)
async def gate_check(
    plate: str,
    db: AsyncSession = Depends(get_db),
) -> ConsignmentForGateCheck:
    """Gate validation: find the active consignment for a truck plate.

    Searches for a consignment that:
    - Matches the plate number (case-insensitive).
    - Has an active status (SCHEDULED, TRUCK_REGISTERED, etc.).
    - Its slot window is within the configurable tolerance window.

    Returns slot times, bay assignment, and current status.
    """
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    window_start = now - timedelta(minutes=settings.GATE_CHECK_LATE_MINUTES)
    window_end = now + timedelta(minutes=settings.GATE_CHECK_EARLY_MINUTES)

    stmt = (
        select(Consignment)
        .where(
            and_(
                Consignment.truck_plate.ilike(plate.upper()),
                Consignment.status.in_(_ACTIVE_STATUSES),
                Consignment.slot_start >= window_start,
                Consignment.slot_start <= window_end,
            )
        )
        .order_by(Consignment.slot_start)
        .limit(1)
    )

    result = await db.execute(stmt)
    consignment = result.scalar_one_or_none()

    if consignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active consignment found for plate '{plate}' within the allowed time window",
        )

    return ConsignmentForGateCheck(
        consignment_id=consignment.id,
        slot_start=consignment.slot_start,
        slot_end=consignment.slot_end,
        bay_code=consignment.bay_code,
        status=consignment.status,
        vendor_id=consignment.vendor_id,
    )


@router.get("/consignments/{consignment_id}", response_model=ConsignmentResponse)
async def get_consignment(
    consignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ConsignmentResponse:
    """Retrieve a single consignment by ID."""
    result = await db.execute(
        select(Consignment).where(Consignment.id == consignment_id)
    )
    consignment = result.scalar_one_or_none()
    if consignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consignment not found")
    return consignment


@router.patch("/consignments/{consignment_id}", response_model=ConsignmentResponse)
async def update_consignment(
    consignment_id: uuid.UUID,
    payload: ConsignmentUpdate,
    db: AsyncSession = Depends(get_db),
) -> ConsignmentResponse:
    """Partial-update a consignment (truck_plate, driver_phone, status)."""
    result = await db.execute(
        select(Consignment).where(Consignment.id == consignment_id)
    )
    consignment = result.scalar_one_or_none()
    if consignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consignment not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(consignment, field, value)

    await db.flush()
    await db.refresh(consignment)
    return consignment


@router.post("/consignments/{consignment_id}/assign-bay", response_model=ConsignmentResponse)
async def assign_bay(
    consignment_id: uuid.UUID,
    bay_id: uuid.UUID = Body(..., embed=True),
    bay_code: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
) -> ConsignmentResponse:
    """Assign or re-assign a bay to a consignment."""
    result = await db.execute(
        select(Consignment).where(Consignment.id == consignment_id)
    )
    consignment = result.scalar_one_or_none()
    if consignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consignment not found")

    consignment.bay_id = bay_id
    consignment.bay_code = bay_code
    await db.flush()
    await db.refresh(consignment)
    return consignment
