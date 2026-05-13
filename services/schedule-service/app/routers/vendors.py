"""Vendor management routes (local copy within schedule-service).

These endpoints allow schedule-service to manage its own vendor registry
independently of the vendor-service microservice.

Endpoints
---------
GET  /api/v1/schedule/vendors         — list vendors
POST /api/v1/schedule/vendors         — create vendor
GET  /api/v1/schedule/vendors/{id}    — get one
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor
from app.schemas.vendor import VendorCreate, VendorResponse

router = APIRouter(tags=["vendors"])


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[VendorResponse]:
    """List all vendors (active by default)."""
    stmt = select(Vendor).order_by(Vendor.vendor_code)
    if active_only:
        stmt = stmt.where(Vendor.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/vendors", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreate,
    db: AsyncSession = Depends(get_db),
) -> VendorResponse:
    """Create a new vendor record."""
    # Check uniqueness
    existing = await db.execute(
        select(Vendor).where(Vendor.vendor_code == payload.vendor_code)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vendor with code '{payload.vendor_code}' already exists",
        )

    vendor = Vendor(**payload.model_dump())
    db.add(vendor)
    await db.flush()
    await db.refresh(vendor)
    return vendor


@router.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> VendorResponse:
    """Retrieve a single vendor by UUID."""
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return vendor
