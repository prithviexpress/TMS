"""Async NATS JetStream consumer for ALPR camera events."""

from __future__ import annotations

import asyncio
import json
import logging

import nats
import nats.js.api
from nats.js.api import ConsumerConfig, DeliverPolicy
from nats.errors import TimeoutError as NatsTimeoutError

from tms_shared.models.events import ALPREvent

from app.database import AsyncSessionLocal
from app.services.gate_logic import process_alpr_entry_event, process_alpr_exit_event

logger = logging.getLogger(__name__)

# NATS subjects consumed by this service
_ALPR_SUBJECTS = [
    "alpr.gate_2.events",
    "alpr.parking_exit.events",
]

# Durable consumer name (must be stable across restarts)
_DURABLE_NAME = "gate-service-alpr"

# Dead-letter queue subject
_DLQ_SUBJECT = "tms.dlq.gate"

# Maximum delivery attempts before sending to DLQ
_MAX_RETRIES = 5


async def _handle_message(
    msg,
    nats_js,
    schedule_service_url: str,
    http_client,
    minio_client,
) -> None:
    """Parse and dispatch a single NATS message.

    Nacks with a short delay on transient errors. After :data:`_MAX_RETRIES`
    delivery attempts the message is forwarded to the DLQ and acked.

    Args:
        msg: The raw NATS message.
        nats_js: Active JetStream context.
        schedule_service_url: Base URL of schedule-service.
        http_client: Shared HTTPX async client.
        minio_client: Boto3 MinIO client.
    """
    num_delivered = msg.metadata.num_delivered if msg.metadata else 1

    try:
        raw = json.loads(msg.data.decode("utf-8"))
        alpr_event = ALPREvent.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse ALPR event from subject %s: %s", msg.subject, exc)
        # Unparseable message → send to DLQ immediately, do not retry
        try:
            await nats_js.publish(
                _DLQ_SUBJECT,
                msg.data,
                headers={"X-Original-Subject": msg.subject, "X-Error": str(exc)[:200]},
            )
        except Exception as dlq_exc:  # noqa: BLE001
            logger.error("Could not publish to DLQ: %s", dlq_exc)
        await msg.ack()
        return

    try:
        async with AsyncSessionLocal() as db:
            if alpr_event.direction == "entry":
                await process_alpr_entry_event(
                    alpr_event=alpr_event,
                    db=db,
                    nats_js=nats_js,
                    schedule_service_url=schedule_service_url,
                    http_client=http_client,
                    minio_client=minio_client,
                )
            elif alpr_event.direction == "exit":
                await process_alpr_exit_event(
                    alpr_event=alpr_event,
                    db=db,
                    nats_js=nats_js,
                )
            else:
                logger.warning(
                    "Unknown direction %r for plate %s – skipping",
                    alpr_event.direction,
                    alpr_event.plate,
                )

            await db.commit()

        await msg.ack()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Error processing ALPR event plate=%s direction=%s (delivery #%d): %s",
            alpr_event.plate,
            alpr_event.direction,
            num_delivered,
            exc,
            exc_info=True,
        )

        if num_delivered >= _MAX_RETRIES:
            logger.error(
                "Plate %s exceeded %d retries – routing to DLQ %s",
                alpr_event.plate,
                _MAX_RETRIES,
                _DLQ_SUBJECT,
            )
            try:
                await nats_js.publish(
                    _DLQ_SUBJECT,
                    msg.data,
                    headers={
                        "X-Original-Subject": msg.subject,
                        "X-Error": str(exc)[:200],
                        "X-Plate": alpr_event.plate,
                    },
                )
            except Exception as dlq_exc:  # noqa: BLE001
                logger.error("Could not publish to DLQ: %s", dlq_exc)
            await msg.ack()
        else:
            # Nack with a 5-second delay to allow transient issues to resolve
            await msg.nak(delay=5)


async def start_alpr_consumer(
    nc: nats.NATS,
    schedule_service_url: str,
    http_client,
    minio_client,
) -> asyncio.Task:
    """Create a JetStream push-subscriber for all ALPR subjects and start it.

    Uses a single durable consumer ``gate-service-alpr`` bound to the
    ``TMS_GATE`` stream (which captures ``alpr.>`` subjects).

    Args:
        nc: Connected NATS client.
        schedule_service_url: Base URL of schedule-service.
        http_client: Shared HTTPX async client.
        minio_client: Boto3 MinIO client.

    Returns:
        The background :class:`asyncio.Task` running the consumer loop.
    """
    js = nc.jetstream()

    # Subscribe to all ALPR subjects via a single durable pull consumer
    # We use subscribe with queue='' to get ordered messages.
    # The TMS_GATE stream covers alpr.> so one subscription per subject is fine.
    subscriptions = []
    for subject in _ALPR_SUBJECTS:
        try:
            sub = await js.subscribe(
                subject,
                durable=_DURABLE_NAME,
                stream="TMS_GATE",
                config=ConsumerConfig(
                    durable_name=_DURABLE_NAME,
                    deliver_policy=DeliverPolicy.NEW,
                    max_deliver=_MAX_RETRIES + 1,
                    ack_wait=30,  # seconds
                ),
            )
            subscriptions.append(sub)
            logger.info("Subscribed to NATS subject %s (durable=%s)", subject, _DURABLE_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to subscribe to %s: %s", subject, exc)
            raise

    async def _consume_loop() -> None:
        """Poll all subscriptions in round-robin and dispatch messages."""
        logger.info("ALPR consumer loop started for %d subjects", len(subscriptions))
        while True:
            for sub in subscriptions:
                try:
                    msg = await sub.next_msg(timeout=0.5)
                    asyncio.create_task(
                        _handle_message(
                            msg=msg,
                            nats_js=js,
                            schedule_service_url=schedule_service_url,
                            http_client=http_client,
                            minio_client=minio_client,
                        )
                    )
                except NatsTimeoutError:
                    # No message available on this subject right now – normal
                    pass
                except Exception as exc:  # noqa: BLE001
                    logger.error("Unexpected error in ALPR consumer loop: %s", exc, exc_info=True)
                    await asyncio.sleep(1)

    task = asyncio.create_task(_consume_loop())
    return task
