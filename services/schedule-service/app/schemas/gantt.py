"""Pydantic schemas for Gantt chart data."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class GanttBlock(BaseModel):
    consignment_id: uuid.UUID
    bay_code: str | None
    slot_start: datetime
    slot_end: datetime
    vendor_name: str
    truck_plate: str | None
    status: str


class GanttResponse(BaseModel):
    date: date
    blocks: list[GanttBlock]
