"""Pydantic request/response schemas for display-service."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


# ── LED schemas ───────────────────────────────────────────────────────────────


class LEDMessageRequest(BaseModel):
    """Payload to send a text message to an LED display panel."""

    Line_1: str = Field(..., max_length=20, description="First line of the LED display")
    Line_2: str = Field("", max_length=20, description="Second line (optional)")
    Line_3: str = Field("", max_length=20, description="Third line (optional)")
    Color: str = Field("GREEN", description="Text colour: GREEN | RED | AMBER | WHITE")
    access_url: str = Field("", description="Panel access URL (passed through to firmware)")
    username: str = Field("", description="Panel auth username")
    password: str = Field("", description="Panel auth password")


class LEDStatusResponse(BaseModel):
    """Current state descriptor for an LED display."""

    display_id: uuid.UUID
    display_code: str
    ip_address: str
    endpoint_path: str
    is_active: bool


# ── K70 schemas ───────────────────────────────────────────────────────────────


class K70LightRequest(BaseModel):
    """Set a single Banner K70 bay light."""

    bay_id: uuid.UUID
    color: Literal["GREEN", "RED", "AMBER", "OFF"]
    mode: Literal["SOLID", "FLASH"]


class K70BulkItem(BaseModel):
    """One entry inside a bulk K70 request."""

    bay_id: uuid.UUID
    color: Literal["GREEN", "RED", "AMBER", "OFF"]
    mode: Literal["SOLID", "FLASH"]


class K70BulkRequest(BaseModel):
    """Set multiple Banner K70 lights in a single call."""

    bays: list[K70BulkItem] = Field(..., min_length=1)


class K70StateResponse(BaseModel):
    """Current K70 light state for a bay."""

    bay_id: uuid.UUID
    bay_code: str
    color: str | None
    mode: str | None
    light_address: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}
