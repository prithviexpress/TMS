"""Pydantic v2 schemas for bay-related API requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Embedded sub-schemas
# ---------------------------------------------------------------------------


class BayOccupancyEmbed(BaseModel):
    """Current occupancy state embedded inside BayResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    movement_id: UUID | None = None
    vendor_id: UUID | None = None
    vendor_name: str | None = None
    truck_plate: str | None = None
    occupied_at: datetime | None = None
    expected_release_at: datetime | None = None
    updated_at: datetime


class BayOccupancyHistoryResponse(BaseModel):
    """Single occupancy history record — used in the Gantt chart endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bay_id: UUID
    bay_code: str
    movement_id: UUID | None = None
    vendor_name: str | None = None
    truck_plate: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_minutes: int | None = None


# ---------------------------------------------------------------------------
# Bay responses
# ---------------------------------------------------------------------------


class BayResponse(BaseModel):
    """Full bay detail including embedded current occupancy state."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bay_code: str
    zone: str | None = None
    sensor_device_eui: str | None = None
    light_address: str | None = None
    light_gateway_ip: str | None = None
    is_active: bool
    created_at: datetime

    # Populated when the bay_occupancy join is present
    current_occupancy: BayOccupancyEmbed | None = None


class BayStatusResponse(BaseModel):
    """Lightweight status snapshot — served from Redis for Mendix polling."""

    bay_code: str
    status: str  # VACANT | OCCUPIED | RESERVED
    vendor_name: str | None = None
    truck_plate: str | None = None
    occupied_at: datetime | None = None
    time_left_minutes: int | None = None  # None when expected_release_at unknown


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class BayAssignRequest(BaseModel):
    """Body for PATCH /bays/{bay_id}/assign — links a truck movement to a bay."""

    movement_id: UUID
    vendor_id: UUID | None = None
    vendor_name: str | None = Field(None, max_length=128)
    truck_plate: str | None = Field(None, max_length=32)
    expected_release_at: datetime | None = None


class BayReleaseRequest(BaseModel):
    """Optional body for PATCH /bays/{bay_id}/release."""

    reason: str | None = Field(None, max_length=256)
