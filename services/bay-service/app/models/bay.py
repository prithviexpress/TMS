"""Bay ORM model — represents a physical dock bay in the MSIL plant."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Bay(Base):
    """A physical dock bay that can be occupied by a truck.

    bay_code examples: 'AR-N1', 'ARC1', 'C2'
    zone examples: 'AR', 'ARC', 'C', 'D', 'E'
    """

    __tablename__ = "bays"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    bay_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    zone: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    # LoRaWAN sensor (Milesight EM400-MUD)
    sensor_device_eui: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)

    # Banner K70 bay indicator light
    light_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    light_gateway_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<Bay {self.bay_code} zone={self.zone} active={self.is_active}>"
