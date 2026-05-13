"""ORM models for LED display panels and command logging."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LEDDisplay(Base):
    """Registered LED display panel.

    Each panel has a unique ``display_code`` (e.g. ``GATE_2_ENTRY``) and a
    known IP address on the plant network.
    """

    __tablename__ = "led_displays"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    display_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    endpoint_path: Mapped[str] = mapped_column(
        String(255), nullable=False, default="/spi/screen/message"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<LEDDisplay code={self.display_code!r} ip={self.ip_address!r}>"


class DisplayCommandLog(Base):
    """Audit log of every command sent to an LED or K70 device."""

    __tablename__ = "display_commands_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # 'LED' | 'K70_LIGHT'
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    command_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<DisplayCommandLog type={self.device_type!r} device={self.device_id!r} "
            f"code={self.response_code}>"
        )
