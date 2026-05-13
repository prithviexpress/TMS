import asyncio
import json
import logging
from datetime import datetime, timezone
from jinja2 import Environment, BaseLoader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
from tms_shared.models.events import TruckArrivedEvent, BayOccupiedEvent, BayVacatedEvent
from app.models.template import NotificationTemplate
from app.models.notification_log import NotificationLog
from app.services.sms_provider import send_sms_msg91
from app.config import get_settings

logger = logging.getLogger(__name__)

jinja_env = Environment(loader=BaseLoader())


def _render(template_body: str, context: dict) -> str:
    tmpl = jinja_env.from_string(template_body)
    return tmpl.render(**context)


async def _get_template(session: AsyncSession, code: str, channel: str = "SMS") -> NotificationTemplate | None:
    result = await session.execute(
        select(NotificationTemplate).where(
            NotificationTemplate.code == code,
            NotificationTemplate.channel == channel,
            NotificationTemplate.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _dispatch(
    session: AsyncSession,
    http_client,
    template_code: str,
    phone: str,
    context_vars: dict,
    trigger_event: str,
    reference_id=None,
):
    settings = get_settings()
    tmpl = await _get_template(session, template_code)
    if not tmpl:
        logger.warning("No active template for code=%s", template_code)
        return

    body = _render(tmpl.body, context_vars)
    msg_id, status = await send_sms_msg91(
        http_client, settings.MSG91_AUTH_KEY, settings.MSG91_SENDER_ID, phone, body
    )
    log = NotificationLog(
        template_code=template_code,
        channel="SMS",
        recipient_phone=phone,
        body_rendered=body,
        trigger_event=trigger_event,
        reference_id=reference_id,
        provider="MSG91",
        provider_msg_id=msg_id,
        status=status,
        sent_at=datetime.now(timezone.utc) if status == "SENT" else None,
    )
    session.add(log)
    await session.commit()


async def run_consumer(js, session_factory: async_sessionmaker, http_client):
    import nats.js.api as jsapi

    subjects = ["tms.gate.truck_arrived", "tms.bay.occupied", "tms.bay.vacated"]
    consumer_cfg = jsapi.ConsumerConfig(durable_name="notification-service", deliver_policy=jsapi.DeliverPolicy.NEW)

    async def _handle(msg):
        subject = msg.subject
        try:
            data = json.loads(msg.data.decode())
            async with session_factory() as session:
                if subject == "tms.gate.truck_arrived":
                    event = TruckArrivedEvent(**data)
                    phone = data.get("driver_phone", "")
                    if not phone:
                        await msg.ack()
                        return
                    if event.action == "allow":
                        ctx = {"truck_plate": event.plate, "bay_code": event.bay_code or "?",
                               "slot_start": event.arrived_at.strftime("%H:%M")}
                        await _dispatch(session, http_client, "TRUCK_ALLOWED", phone, ctx, subject, event.movement_id)
                    elif event.action == "hold":
                        ctx = {"truck_plate": event.plate, "minutes_to_slot": event.minutes_to_slot or 0}
                        await _dispatch(session, http_client, "TRUCK_HOLD", phone, ctx, subject, event.movement_id)
                    elif event.action == "reject":
                        ctx = {"truck_plate": event.plate, "rejection_reason": event.rejection_reason or "Not in schedule"}
                        await _dispatch(session, http_client, "TRUCK_REJECT", phone, ctx, subject, event.movement_id)

                elif subject == "tms.bay.occupied":
                    event = BayOccupiedEvent(**data)
                    phone = data.get("vendor_phone", "")
                    if phone:
                        ctx = {"bay_code": event.bay_code}
                        await _dispatch(session, http_client, "BAY_OCCUPIED", phone, ctx, subject, event.movement_id)

                elif subject == "tms.bay.vacated":
                    event = BayVacatedEvent(**data)
                    phone = data.get("vendor_phone", "")
                    if phone:
                        ctx = {"bay_code": event.bay_code, "duration_minutes": event.duration_minutes or 0}
                        await _dispatch(session, http_client, "BAY_VACATED", phone, ctx, subject, event.movement_id)

            await msg.ack()
        except Exception as exc:
            logger.error("Consumer error on %s: %s", subject, exc)
            await msg.nak()

    try:
        for stream_name, filter_subject in [
            ("TMS_GATE", "tms.gate.truck_arrived"),
            ("TMS_BAY", "tms.bay.occupied"),
            ("TMS_BAY", "tms.bay.vacated"),
        ]:
            sub = await js.subscribe(filter_subject, durable="notification-service", stream=stream_name)
            asyncio.create_task(_process_subscription(sub, _handle))
        logger.info("Notification event consumer started")
    except Exception as exc:
        logger.error("Failed to start notification consumer: %s", exc)


async def _process_subscription(sub, handler):
    async for msg in sub.messages:
        await handler(msg)
