"""BayOccupancy ORM model — one active record per bay (current live state)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BayOccupancy(Base):
    """Current occupancy state for a bay.

    There is exactly one row per bay (enforced by the UNIQUE constraint on
    bay_id).  The row is inserted during seeding/first-use and updated in place
    as the bay transitions between states.

    Status values: 'VACANT' | 'OCCUPIED' | 'RESERVED'
    """

    __tablename__ = "bay_occupancy"

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
        unique=True,   # one active record per bay
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="VACANT",
        server_default="VACANT",
    )

    # Optional link back to the truck movement record (gate-service)
    movement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    truck_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)

    occupied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # Relationship back to bay (lazy load is fine — we only need it occasionally)
    bay = relationship("Bay", lazy="select", foreign_keys=[bay_id])

    def __repr__(self) -> str:
        return f"<BayOccupancy bay_id={self.bay_id} status={self.status}>"
