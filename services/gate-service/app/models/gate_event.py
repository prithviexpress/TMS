"""ORM model for the gate_events table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class GateEvent(Base):
    """Raw ALPR camera event stored verbatim from the NATS message.

    Every ALPR trigger — whether entry or exit, regardless of whether the
    plate is recognised — creates one :class:`GateEvent` row so there is a
    complete audit trail.
    """

    __tablename__ = "gate_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 'gate_2' | 'parking_exit'
    camera_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'entry' | 'exit'
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    truck_movement: Mapped["TruckMovement | None"] = relationship(  # noqa: F821
        "TruckMovement",
        back_populates="gate_event",
        uselist=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GateEvent plate={self.plate_number!r} dir={self.direction!r}>"
