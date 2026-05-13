"""ORM model for the trucks table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Truck(Base):
    """Represents a known truck (vehicle) in the system.

    A Truck record is created automatically the first time a plate is seen at
    the gate, or can be pre-registered by a vendor / admin.
    """

    __tablename__ = "trucks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    driver_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

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

    # Relationships (back-populated from TruckMovement)
    movements: Mapped[list["TruckMovement"]] = relationship(  # noqa: F821
        "TruckMovement",
        back_populates="truck",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Truck plate={self.plate_number!r}>"
