"""Pydantic schemas for vendor-service."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Vendor CRUD schemas ────────────────────────────────────────────────────────


class VendorCreate(BaseModel):
    vendor_code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    contact_name: str | None = None
    contact_phone: str | None = None
    whatsapp_number: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    is_active: bool = True
    # Caller may supply a pre-generated token; if omitted one will be created
    registration_token: str | None = None


class VendorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    contact_name: str | None = None
    contact_phone: str | None = None
    whatsapp_number: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    is_active: bool | None = None
    registration_token: str | None = None


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    whatsapp_number: str | None
    email: str | None
    address: str | None
    city: str | None
    is_active: bool
    registration_token: str | None
    created_at: datetime
    updated_at: datetime


# ── Truck-registration schemas ─────────────────────────────────────────────────


class TruckRegistrationRequest(BaseModel):
    consignment_id: uuid.UUID
    truck_plate: str = Field(..., min_length=1, max_length=20)
    driver_name: str | None = None
    driver_phone: str = Field(..., min_length=6, max_length=20)


class TruckRegistrationResponse(BaseModel):
    consignment_id: uuid.UUID
    truck_plate: str
    driver_phone: str
    slot_start: datetime | None = None
    bay_code: str | None = None
    message: str
