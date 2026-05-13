import uuid
from datetime import datetime
from pydantic import BaseModel


class TemplateCreate(BaseModel):
    code: str
    channel: str
    body: str
    language: str = "en"


class TemplateResponse(BaseModel):
    id: uuid.UUID
    code: str
    channel: str
    body: str
    language: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualSendRequest(BaseModel):
    template_code: str
    channel: str
    phone: str
    context_vars: dict = {}


class NotificationLogResponse(BaseModel):
    id: uuid.UUID
    template_code: str | None
    channel: str
    recipient_phone: str
    body_rendered: str
    trigger_event: str | None
    provider: str | None
    status: str | None
    sent_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
