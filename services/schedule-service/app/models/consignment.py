"""Consignment ORM model — one row = one truck delivery slot."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Consignment(Base):
    __tablename__ = "consignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    nagare_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nagare_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    bay_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # denormalized from bay-service
    bay_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    part_numbers: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    slot_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    truck_plate: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    driver_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="SCHEDULED",
        index=True,
    )
    # Valid statuses:
    # SCHEDULED | TRUCK_REGISTERED | TRUCK_AT_GATE | TRUCK_PROCEEDING
    # TRUCK_AT_BAY | COMPLETED | MISSED | RESCHEDULED
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    nagare: Mapped["NagareSchedule | None"] = relationship(  # noqa: F821
        "NagareSchedule", back_populates="consignments", lazy="raise"
    )
    vendor: Mapped["Vendor"] = relationship(  # noqa: F821
        "Vendor", back_populates="consignments", lazy="raise"
    )
