"""Pydantic schemas for GateEvent endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GateEventResponse(BaseModel):
    """Gate event record returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate_number: str
    camera_id: str
    direction: str
    confidence: float | None
    image_url: str | None
    raw_payload: dict
    detected_at: datetime
    created_at: datetime
