"""SensorReading ORM model — raw LoRaWAN payload from Milesight EM400-MUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SensorReading(Base):
    """Persisted raw reading from a Milesight EM400-MUD occupancy sensor.

    Every Chirpstack webhook call results in one SensorReading row, regardless
    of whether the occupancy state changed.  This provides a full audit trail
    and supports diagnostics/replays.
    """

    __tablename__ = "sensor_readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    device_eui: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # May be NULL if the DevEUI is not registered to any bay
    bay_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bays.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Decoded occupancy verdict
    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Physical sensor values (may be absent in some firmware versions)
    distance_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Full webhook body stored as JSONB for replay / debugging
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<SensorReading eui={self.device_eui} occupied={self.occupied} "
            f"dist={self.distance_mm}mm at={self.received_at}>"
        )
