"""Pydantic schemas for Truck endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TruckCreate(BaseModel):
    """Payload accepted when manually registering a truck."""

    plate_number: str = Field(..., min_length=1, max_length=20, examples=["MH02AB1234"])
    vendor_id: uuid.UUID | None = None
    driver_name: str | None = Field(None, max_length=120)
    driver_phone: str | None = Field(None, max_length=20)


class TruckStatusPatch(BaseModel):
    """Payload for status override on a truck movement."""

    status: str = Field(..., examples=["proceeding", "rejected"])
    rejection_reason: str | None = None


class TruckResponse(BaseModel):
    """Full truck record returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate_number: str
    vendor_id: uuid.UUID | None
    driver_name: str | None
    driver_phone: str | None
    created_at: datetime
    updated_at: datetime
