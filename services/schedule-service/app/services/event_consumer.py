"""NATS event consumer for schedule-service.

Subscribes to:
  tms.gate.truck_arrived  → TRUCK_AT_GATE
  tms.bay.occupied        → TRUCK_AT_BAY
  tms.bay.vacated         → COMPLETED
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import nats
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.consignment import Consignment

logger = logging.getLogger(__name__)

# Maps NATS subject → new consignment status
_SUBJECT_STATUS_MAP: dict[str, str] = {
    "tms.gate.truck_arrived": "TRUCK_AT_GATE",
    "tms.bay.occupied": "TRUCK_AT_BAY",
    "tms.bay.vacated": "COMPLETED",
}


def _extract_consignment_id(payload: dict[str, Any], subject: str) -> uuid.UUID | None:
    """Try to extract consignment_id from the event payload."""
    raw = payload.get("consignment_id") or payload.get("consignmentId")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            logger.warning("Invalid consignment_id in %s payload: %r", subject, raw)
    return None


def _extract_truck_plate(payload: dict[str, Any]) -> str | None:
    return payload.get("truck_plate") or payload.get("plate") or payload.get("licensePlate")


async def _update_consignment_status(
    consignment_id: uuid.UUID | None,
    truck_plate: str | None,
    new_status: str,
) -> None:
    """Update the consignment status in the database.

    Lookup is attempted by consignment_id first; falls back to truck_plate when
    consignment_id is absent (e.g. gate events before a consignment match).
    """
    async with AsyncSessionLocal() as session:
        stmt = None
        if consignment_id:
            stmt = select(Consignment).where(Consignment.id == consignment_id)
        elif truck_plate:
            # Find the most recent active consignment for this plate
            stmt = (
                select(Consignment)
                .where(
                    Consignment.truck_plate == truck_plate,
                    Consignment.status.notin_(["COMPLETED", "MISSED", "RESCHEDULED"]),
                )
                .order_by(Consignment.slot_start.desc())
                .limit(1)
            )

        if stmt is None:
            logger.warning("Cannot update consignment: no consignment_id or truck_plate in payload")
            return

        result = await session.execute(stmt)
        consignment = result.scalar_one_or_none()

        if consignment is None:
            logger.info(
                "No consignment found for id=%s plate=%s — status update skipped",
                consignment_id,
                truck_plate,
            )
            return

        old_status = consignment.status
        consignment.status = new_status
        await session.commit()
        logger.info(
            "Consignment %s status: %s → %s",
            consignment.id,
            old_status,
            new_status,
        )


async def _handle_message(msg: nats.aio.msg.Msg) -> None:
    """Parse and dispatch an incoming NATS message."""
    subject = msg.subject
    new_status = _SUBJECT_STATUS_MAP.get(subject)
    if new_status is None:
        logger.debug("Ignoring unhandled subject: %s", subject)
        return

    try:
        payload: dict[str, Any] = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Failed to decode message on %s: %s", subject, exc)
        return

    consignment_id = _extract_consignment_id(payload, subject)
    truck_plate = _extract_truck_plate(payload)

    logger.debug(
        "Event %s — consignment_id=%s plate=%s → %s",
        subject,
        consignment_id,
        truck_plate,
        new_status,
    )

    try:
        await _update_consignment_status(consignment_id, truck_plate, new_status)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error processing event %s: %s", subject, exc)


async def start_event_consumer(nc: nats.NATS) -> None:
    """Subscribe to all TMS events and process them indefinitely.

    This coroutine is intended to be launched as a background :func:`asyncio.Task`
    from the application lifespan.

    Args:
        nc: A connected :class:`nats.NATS` client.
    """
    subscriptions = []

    for subject in _SUBJECT_STATUS_MAP:
        sub = await nc.subscribe(subject, cb=_handle_message)
        subscriptions.append(sub)
        logger.info("Subscribed to NATS subject: %s", subject)

    logger.info("Event consumer started — listening on %d subjects", len(subscriptions))

    # Keep the task alive until cancelled
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("Event consumer cancelled — unsubscribing")
        for sub in subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:  # noqa: BLE001
                pass
        raise
