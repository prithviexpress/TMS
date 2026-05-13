"""Pydantic schemas for TruckMovement endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TruckMovementResponse(BaseModel):
    """Full truck movement record returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    truck_id: uuid.UUID | None
    consignment_id: uuid.UUID | None
    plate_number: str
    gate_event_id: uuid.UUID | None
    status: str
    gate_in_at: datetime | None
    bay_in_at: datetime | None
    bay_out_at: datetime | None
    gate_out_at: datetime | None
    nagare_slot_start: datetime | None
    nagare_slot_end: datetime | None
    minutes_to_slot: int | None
    bay_code: str | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class ManualEntryRequest(BaseModel):
    """Payload for the admin manual-entry fallback endpoint.

    All fields except ``plate_number`` are optional so the operator can
    provide as much information as is available at the time.
    """

    plate_number: str = Field(..., min_length=1, max_length=20, examples=["MH02AB1234"])
    vendor_id: uuid.UUID | None = None
    consignment_id: uuid.UUID | None = None
    bay_code: str | None = None
    driver_name: str | None = Field(None, max_length=120)
    driver_phone: str | None = Field(None, max_length=20)
