"""Pydantic schemas for Consignment."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Valid consignment statuses
ConsignmentStatus = Literal[
    "SCHEDULED",
    "TRUCK_REGISTERED",
    "TRUCK_AT_GATE",
    "TRUCK_PROCEEDING",
    "TRUCK_AT_BAY",
    "COMPLETED",
    "MISSED",
    "RESCHEDULED",
]


class ConsignmentCreate(BaseModel):
    nagare_id: uuid.UUID | None = None
    vendor_id: uuid.UUID
    bay_id: uuid.UUID | None = None
    bay_code: str | None = None
    part_numbers: list[str] = Field(default_factory=list)
    slot_start: datetime
    slot_end: datetime
    truck_plate: str | None = None
    driver_phone: str | None = None
    status: ConsignmentStatus = "SCHEDULED"


class ConsignmentUpdate(BaseModel):
    truck_plate: str | None = None
    driver_phone: str | None = None
    status: ConsignmentStatus | None = None


class ConsignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nagare_id: uuid.UUID | None
    vendor_id: uuid.UUID
    bay_id: uuid.UUID | None
    bay_code: str | None
    part_numbers: list[str]
    slot_start: datetime
    slot_end: datetime
    truck_plate: str | None
    driver_phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ConsignmentForGateCheck(BaseModel):
    """Minimal projection returned to gate-service for truck validation."""

    model_config = ConfigDict(from_attributes=True)

    consignment_id: uuid.UUID
    slot_start: datetime
    slot_end: datetime
    bay_code: str | None
    status: str
    vendor_id: uuid.UUID
