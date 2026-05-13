"""NATS JetStream consumer — reacts to gate-service events.

Subscribed subject: ``tms.gate.truck_arrived``

When a truck_arrived event with ``action == "allow"`` arrives and includes a
``bay_code``, the consumer looks up the bay and calls ``assign_bay`` to
RESERVE it ahead of the truck's physical arrival.
"""

from __future__ import annotations

import json
import logging

from nats.aio.client import Client as NATSClient
from nats.js.api import ConsumerConfig, DeliverPolicy
from sqlalchemy import select

import redis.asyncio as aioredis

from app.config import settings
from app.models.bay import Bay
from app.services.occupancy import assign_bay
from tms_shared.models.events import TruckArrivedEvent

logger = logging.getLogger(__name__)

_CONSUMER_NAME = "bay-service-gate-consumer"
_SUBJECT = "tms.gate.truck_arrived"


async def start_event_consumer(
    nc: NATSClient,
    redis: aioredis.Redis,
    db_session_factory,
) -> None:
    """Subscribe to ``tms.gate.truck_arrived`` and handle truck-allowed events.

    Args:
        nc: Connected NATS client.
        redis: Shared Redis connection pool.
        db_session_factory: Callable that returns an async context manager
            yielding an ``AsyncSession`` (i.e. ``AsyncSessionLocal``).
    """
    js = nc.jetstream()

    async def _handle(msg) -> None:  # type: ignore[no-untyped-def]
        try:
            body = json.loads(msg.data.decode())
            event = TruckArrivedEvent.model_validate(body)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to parse tms.gate.truck_arrived message: %s", exc)
            await msg.ack()
            return

        if event.action != "allow":
            logger.debug("Ignoring gate event with action=%s", event.action)
            await msg.ack()
            return

        if not event.bay_code:
            logger.debug("truck_arrived allow event has no bay_code — skipping reservation")
            await msg.ack()
            return

        logger.info(
            "Gate event: truck %s allowed → reserving bay %s (movement=%s)",
            event.plate,
            event.bay_code,
            event.movement_id,
        )

        async with db_session_factory() as db:
            result = await db.execute(
                select(Bay).where(Bay.bay_code == event.bay_code, Bay.is_active.is_(True))
            )
            bay = result.scalar_one_or_none()
            if bay is None:
                logger.warning("Bay %s not found or inactive — cannot reserve", event.bay_code)
                await msg.ack()
                return

            try:
                await assign_bay(
                    db=db,
                    redis=redis,
                    nc=nc,
                    bay=bay,
                    movement_id=event.movement_id,
                    vendor_id=event.vendor_id,
                    vendor_name=None,   # gate-service doesn't include vendor_name yet
                    truck_plate=event.plate,
                    expected_release_at=None,
                    display_service_url=settings.DISPLAY_SERVICE_URL,
                    status="RESERVED",
                )
                logger.info("Bay %s reserved for movement %s", event.bay_code, event.movement_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to reserve bay %s: %s", event.bay_code, exc)

        await msg.ack()

    try:
        config = ConsumerConfig(
            name=_CONSUMER_NAME,
            deliver_policy=DeliverPolicy.NEW,
            filter_subject=_SUBJECT,
            ack_wait=30,
            max_deliver=3,
        )
        await js.subscribe(
            _SUBJECT,
            cb=_handle,
            stream="TMS_GATE",
            config=config,
            manual_ack=True,
        )
        logger.info("NATS consumer subscribed to %s", _SUBJECT)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start NATS consumer for %s: %s", _SUBJECT, exc)
        raise
