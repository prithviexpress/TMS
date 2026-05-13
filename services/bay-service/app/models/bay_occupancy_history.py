"""BayOccupancyHistory ORM model — closed occupancy periods for Gantt charts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BayOccupancyHistory(Base):
    """Immutable record of a completed (or in-progress) bay occupancy period.

    A new row is written when a bay transitions to OCCUPIED.
    The row is *closed* (ended_at + duration_minutes computed) when the bay
    transitions back to VACANT or RESERVED.

    This table drives the Gantt-chart view in Mendix.
    """

    __tablename__ = "bay_occupancy_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bay_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Denormalised for query performance (avoids a JOIN on every Gantt load)
    movement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    truck_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Rounded to the nearest minute; computed when the row is closed
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<BayOccupancyHistory bay={self.bay_code} "
            f"started={self.started_at} ended={self.ended_at}>"
        )
