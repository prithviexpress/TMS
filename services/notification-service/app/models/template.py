import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # 'SMS' | 'WHATSAPP'
    body: Mapped[str] = mapped_column(Text, nullable=False)  # Jinja2 template
    language: Mapped[str] = mapped_column(String(10), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
