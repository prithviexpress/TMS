"""Pydantic schemas for Vendor."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VendorCreate(BaseModel):
    vendor_code: str
    name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    whatsapp_number: str | None = None
    is_active: bool = True


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    whatsapp_number: str | None
    is_active: bool
    created_at: datetime
