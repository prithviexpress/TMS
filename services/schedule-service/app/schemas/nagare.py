"""Pydantic schemas for NagareSchedule."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class NagareCreate(BaseModel):
    schedule_date: date
    shift: str | None = None
    uploaded_by: str | None = None
    raw_file_url: str | None = None
    is_published: bool = False


class NagareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_date: date
    shift: str | None
    uploaded_by: str | None
    raw_file_url: str | None
    is_published: bool
    created_at: datetime
