import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_code: Mapped[str | None] = mapped_column(String(50))
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    body_rendered: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(String(100))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_msg_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(20))  # SENT | DELIVERED | FAILED
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
