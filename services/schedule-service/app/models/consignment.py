"""Consignment ORM model — one row = one truck delivery slot (one Nagare line)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Consignment(Base):
    __tablename__ = "consignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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

    # ------------------------------------------------------------------
    # Nagare schedule fields (from the uploaded Nagare file)
    # ------------------------------------------------------------------
    schedule_no: Mapped[str | None] = mapped_column(
        String(30), nullable=True, index=True
    )  # e.g. "16P6412043310WR1" — Nagare system's own ID
    item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bay_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    bay_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # soft ref to bay-service — no FK (cross-DB)
    slot_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nag_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # planned qty

    # ------------------------------------------------------------------
    # Truck / driver fields (filled when truck is registered)
    # ------------------------------------------------------------------
    truck_plate: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    driver_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ------------------------------------------------------------------
    # GR / actual receipt fields (filled at parking counter + bay)
    # ------------------------------------------------------------------
    consignment_no: Mapped[str | None] = mapped_column(
        String(30), nullable=True, index=True
    )  # SAP GR number e.g. "72564727" — filled by clerk at parking counter
    gate_entry_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejection_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    utl_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------
    # Planning flags
    # ------------------------------------------------------------------
    is_urgent: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    is_emergency: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )

    # ------------------------------------------------------------------
    # Status state machine
    # SCHEDULED → TRUCK_REGISTERED → TRUCK_AT_GATE → IN_PARKING
    # → CALLED_TO_BAY → TRUCK_AT_BAY → COMPLETED | MISSED | RESCHEDULED
    # ------------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="SCHEDULED", index=True
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    material_entry_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # when clerk did GR entry at parking counter
    material_entry_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
