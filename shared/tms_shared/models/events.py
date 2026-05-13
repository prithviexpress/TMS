"""Pydantic v2 models for all TMS NATS event payloads.

These models form the inter-service contract.  Every NATS publisher and
subscriber must serialise/deserialise messages using these types.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ALPREvent(BaseModel):
    """Automatic Licence-Plate Recognition camera event.

    Published to: ``alpr.<camera_id>.events``
    """

    plate: str
    direction: str  # "entry" | "exit"
    confidence: float
    camera_id: str
    image_url: str | None = None
    ts: datetime


class TruckArrivedEvent(BaseModel):
    """Gate-service event emitted when a truck is processed at the gate.

    Published to: ``tms.gate.truck_arrived``
    """

    movement_id: UUID
    plate: str
    vendor_id: UUID | None = None
    consignment_id: UUID | None = None
    action: str  # "allow" | "hold" | "reject"
    bay_code: str | None = None
    minutes_to_slot: int | None = None
    rejection_reason: str | None = None
    arrived_at: datetime


class TruckDepartedEvent(BaseModel):
    """Gate-service event emitted when a truck leaves the facility.

    Published to: ``tms.gate.truck_departed``
    """

    movement_id: UUID
    plate: str
    gate_out_at: datetime


class BayOccupiedEvent(BaseModel):
    """Bay-service event emitted when a bay becomes occupied.

    Published to: ``tms.bay.occupied``
    """

    bay_id: UUID
    bay_code: str
    movement_id: UUID | None = None
    truck_plate: str | None = None
    vendor_id: UUID | None = None
    vendor_name: str | None = None
    occupied_at: datetime


class BayVacatedEvent(BaseModel):
    """Bay-service event emitted when a bay is vacated.

    Published to: ``tms.bay.vacated``
    """

    bay_id: UUID
    bay_code: str
    movement_id: UUID | None = None
    duration_minutes: int | None = None
    vacated_at: datetime


class BaySensorConflictEvent(BaseModel):
    """Bay-service event for IoT sensor conflicts (ghost occupancy etc.).

    Published to: ``tms.bay.sensor_conflict``
    """

    bay_id: UUID
    bay_code: str
    device_eui: str
    detected_at: datetime


class ConsignmentUpdatedEvent(BaseModel):
    """Schedule-service event when a consignment status changes.

    Published to: ``tms.schedule.consignment_updated``
    """

    consignment_id: UUID
    status: str
    bay_code: str | None = None
    slot_start: datetime | None = None
    updated_at: datetime


class TruckRegisteredEvent(BaseModel):
    """Schedule-service event when a vendor registers a truck for a slot.

    Published to: ``tms.schedule.truck_registered``
    """

    consignment_id: UUID
    vendor_id: UUID
    truck_plate: str
    driver_phone: str
    slot_start: datetime
    bay_code: str | None = None
