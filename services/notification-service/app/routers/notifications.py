from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.template import NotificationTemplate
from app.models.notification_log import NotificationLog
from app.schemas.notification import (
    TemplateCreate, TemplateResponse,
    ManualSendRequest, NotificationLogResponse,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationTemplate).order_by(NotificationTemplate.code))
    return result.scalars().all()


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(body: TemplateCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(NotificationTemplate).where(NotificationTemplate.code == body.code))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Template '{body.code}' already exists")
    tmpl = NotificationTemplate(**body.model_dump())
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


@router.get("/logs", response_model=list[NotificationLogResponse])
async def list_logs(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationLog)
        .order_by(NotificationLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/send")
async def manual_send(body: ManualSendRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationTemplate).where(NotificationTemplate.code == body.template_code)
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(404, f"Template '{body.template_code}' not found")
    from jinja2 import Environment, BaseLoader
    env = Environment(loader=BaseLoader())
    rendered = env.from_string(tmpl.body).render(**body.context_vars)
    log = NotificationLog(
        template_code=body.template_code,
        channel=body.channel,
        recipient_phone=body.phone,
        body_rendered=rendered,
        trigger_event="manual",
        status="QUEUED",
    )
    db.add(log)
    await db.commit()
    return {"status": "queued", "body_preview": rendered[:100]}
