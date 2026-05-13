"""Nagare (production schedule) ORM model."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NagareSchedule(Base):
    __tablename__ = "nagare_schedules"

    __table_args__ = (
        UniqueConstraint("schedule_date", "shift", name="uq_nagare_date_shift"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # 'A', 'B', 'C', 'FULL'
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_file_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    consignments: Mapped[list["Consignment"]] = relationship(  # noqa: F821
        "Consignment", back_populates="nagare", lazy="raise"
    )
