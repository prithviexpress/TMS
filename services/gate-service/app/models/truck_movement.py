"""ORM model for the truck_movements table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# Valid status values
MOVEMENT_STATUSES = ("waiting", "proceeding", "at_bay", "departed", "rejected")


class TruckMovement(Base):
    """Lifecycle record that tracks a single truck visit end-to-end.

    Created when a truck arrives at the gate and updated as the truck moves
    through the facility (bay assignment, departure, etc.).
    """

    __tablename__ = "truck_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign keys
    truck_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trucks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gate_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gate_events.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Denormalised / cross-service references
    consignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # State machine
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting", index=True)

    # Timestamps
    gate_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bay_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bay_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gate_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Nagare (schedule) slot info
    nagare_slot_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nagare_slot_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Positive = early, negative = late (in minutes relative to slot_start)
    minutes_to_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Bay assignment
    bay_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Rejection
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    truck: Mapped["Truck | None"] = relationship(  # noqa: F821
        "Truck",
        back_populates="movements",
    )
    gate_event: Mapped["GateEvent | None"] = relationship(  # noqa: F821
        "GateEvent",
        back_populates="truck_movement",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TruckMovement plate={self.plate_number!r} status={self.status!r}>"
