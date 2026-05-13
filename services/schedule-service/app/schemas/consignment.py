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
    "IN_PARKING",
    "CALLED_TO_BAY",
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
    slot_start: datetime
    slot_end: datetime
    truck_plate: str | None = None
    driver_phone: str | None = None
    driver_name: str | None = None
    status: ConsignmentStatus = "SCHEDULED"
    schedule_no: str | None = None
    item_code: str | None = None
    item_name: str | None = None
    nag_qty: int | None = None
    consignment_no: str | None = None
    gate_entry_qty: int | None = None
    received_qty: int | None = None
    rejection_qty: int = 0
    utl_qty: int | None = None
    is_urgent: bool = False
    is_emergency: bool = False
    material_entry_time: datetime | None = None
    material_entry_by: str | None = None


class ConsignmentUpdate(BaseModel):
    truck_plate: str | None = None
    driver_phone: str | None = None
    driver_name: str | None = None
    status: ConsignmentStatus | None = None
    consignment_no: str | None = None
    gate_entry_qty: int | None = None
    received_qty: int | None = None
    rejection_qty: int | None = None
    utl_qty: int | None = None
    is_urgent: bool | None = None
    is_emergency: bool | None = None
    material_entry_time: datetime | None = None
    material_entry_by: str | None = None


class ConsignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nagare_id: uuid.UUID | None
    vendor_id: uuid.UUID
    bay_id: uuid.UUID | None
    bay_code: str | None
    slot_start: datetime
    slot_end: datetime
    truck_plate: str | None
    driver_phone: str | None
    driver_name: str | None
    status: str
    schedule_no: str | None
    item_code: str | None
    item_name: str | None
    nag_qty: int | None
    consignment_no: str | None
    gate_entry_qty: int | None
    received_qty: int | None
    rejection_qty: int
    utl_qty: int | None
    is_urgent: bool
    is_emergency: bool
    material_entry_time: datetime | None
    material_entry_by: str | None
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
