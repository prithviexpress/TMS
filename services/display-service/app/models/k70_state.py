"""ORM model for the current state of each Banner K70 bay light."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.led_display import Base


class K70LightState(Base):
    """One row per physical bay — tracks the last-known K70 light state.

    ``bay_id`` is the primary key so an upsert on the bay's UUID always
    results in a single row per bay.
    """

    __tablename__ = "k70_light_states"

    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    bay_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 'GREEN' | 'RED' | 'AMBER' | 'OFF'
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 'SOLID' | 'FLASH'
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    light_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<K70LightState bay={self.bay_code!r} color={self.color!r} mode={self.mode!r}>"
        )
