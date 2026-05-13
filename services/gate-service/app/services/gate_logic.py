"""Core gate business logic: arrival evaluation and ALPR event processing."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tms_shared.models.events import ALPREvent, TruckArrivedEvent, TruckDepartedEvent

from app.models.gate_event import GateEvent
from app.models.truck import Truck
from app.models.truck_movement import TruckMovement

logger = logging.getLogger(__name__)

# Early-arrival hold threshold (minutes before slot).
# Late arrivals are ALWAYS allowed — no rejection for lateness.
# If the scheduled bay is occupied when a late truck is called, schedule-service
# redirects it to an emergency bay via the conflict-resolution endpoint.
_TOO_EARLY_THRESHOLD = 60   # > 60 min before slot → hold in parking


async def evaluate_truck_arrival(
    plate: str,
    arrival_time: datetime,
    schedule_service_url: str,
    http_client: httpx.AsyncClient,
) -> dict:
    """Query schedule-service and apply Nagare window logic.

    Args:
        plate: The truck licence plate number.
        arrival_time: The timestamp at which the truck arrived at the gate.
        schedule_service_url: Base URL of the schedule-service, e.g.
            ``"http://schedule-service:8003"``.
        http_client: A shared :class:`httpx.AsyncClient` instance.

    Returns:
        A dict with keys:
        ``action`` (``"allow"`` | ``"hold"`` | ``"reject"``).
        ``"reject"`` only when plate is not in Nagare or has no active consignment —
        never for lateness. Late trucks get ``"allow"``; bay conflict (occupied slot)
        is resolved by schedule-service redirecting to an emergency bay.
        Also: ``consignment_id``, ``bay_code``, ``bay_id``, ``vendor_id``,
        ``minutes_to_slot`` (int | None), ``nagare_slot_start`` (datetime | None),
        ``nagare_slot_end`` (datetime | None), ``rejection_reason`` (str | None).
    """
    consignment_url = (
        f"{schedule_service_url}/api/v1/schedule/consignments/check/{plate}"
    )

    try:
        response = await http_client.get(consignment_url, timeout=10.0)
    except httpx.RequestError as exc:
        logger.error("HTTP error querying schedule-service for plate %s: %s", plate, exc)
        return {
            "action": "reject",
            "consignment_id": None,
            "bay_code": None,
            "bay_id": None,
            "vendor_id": None,
            "minutes_to_slot": None,
            "nagare_slot_start": None,
            "nagare_slot_end": None,
            "rejection_reason": "Schedule service unreachable",
        }

    if response.status_code == 404:
        logger.info("Plate %s not found in schedule (404)", plate)
        return {
            "action": "reject",
            "consignment_id": None,
            "bay_code": None,
            "bay_id": None,
            "vendor_id": None,
            "minutes_to_slot": None,
            "nagare_slot_start": None,
            "nagare_slot_end": None,
            "rejection_reason": "Not in schedule",
        }

    if response.status_code != 200:
        logger.error(
            "Unexpected status %d from schedule-service for plate %s",
            response.status_code,
            plate,
        )
        return {
            "action": "reject",
            "consignment_id": None,
            "bay_code": None,
            "bay_id": None,
            "vendor_id": None,
            "minutes_to_slot": None,
            "nagare_slot_start": None,
            "nagare_slot_end": None,
            "rejection_reason": f"Schedule service error (HTTP {response.status_code})",
        }

    data = response.json()

    # A response with no active consignment is treated as "not in schedule"
    if not data or data.get("status") not in ("scheduled", "active", "confirmed"):
        logger.info("Plate %s has no active consignment (status=%s)", plate, data.get("status"))
        return {
            "action": "reject",
            "consignment_id": data.get("consignment_id"),
            "bay_code": data.get("bay_code"),
            "bay_id": data.get("bay_id"),
            "vendor_id": data.get("vendor_id"),
            "minutes_to_slot": None,
            "nagare_slot_start": None,
            "nagare_slot_end": None,
            "rejection_reason": "No active consignment",
        }

    # Parse slot times — schedule-service returns ISO-8601 strings
    slot_start_raw = data.get("slot_start")
    slot_end_raw = data.get("slot_end")

    if not slot_start_raw:
        return {
            "action": "reject",
            "consignment_id": data.get("consignment_id"),
            "bay_code": data.get("bay_code"),
            "bay_id": data.get("bay_id"),
            "vendor_id": data.get("vendor_id"),
            "minutes_to_slot": None,
            "nagare_slot_start": None,
            "nagare_slot_end": None,
            "rejection_reason": "No slot time assigned",
        }

    slot_start: datetime = datetime.fromisoformat(slot_start_raw)
    slot_end: datetime = datetime.fromisoformat(slot_end_raw) if slot_end_raw else None

    # Normalise to UTC-aware for arithmetic
    if slot_start.tzinfo is None:
        slot_start = slot_start.replace(tzinfo=timezone.utc)
    if arrival_time.tzinfo is None:
        arrival_time = arrival_time.replace(tzinfo=timezone.utc)

    minutes_to_slot = int((slot_start - arrival_time).total_seconds() / 60)

    # Decision tree
    # Late arrivals are always allowed — bay conflict is resolved by schedule-service
    # (redirects to emergency bay if the scheduled bay is now occupied).
    if minutes_to_slot > _TOO_EARLY_THRESHOLD:
        action = "hold"
        rejection_reason = f"Arrived too early (>{_TOO_EARLY_THRESHOLD} min before slot)"
    else:
        action = "allow"
        rejection_reason = None

    logger.info(
        "Plate %s: minutes_to_slot=%d → action=%s",
        plate,
        minutes_to_slot,
        action,
    )

    return {
        "action": action,
        "consignment_id": data.get("consignment_id"),
        "bay_code": data.get("bay_code"),
        "bay_id": data.get("bay_id"),
        "vendor_id": data.get("vendor_id"),
        "minutes_to_slot": minutes_to_slot,
        "nagare_slot_start": slot_start,
        "nagare_slot_end": slot_end,
        "rejection_reason": rejection_reason,
    }


async def _get_or_create_truck(
    db: AsyncSession,
    plate: str,
    vendor_id: str | None = None,
) -> Truck:
    """Fetch existing Truck by plate or create a new one."""
    result = await db.execute(select(Truck).where(Truck.plate_number == plate))
    truck = result.scalars().first()

    if truck is None:
        truck = Truck(
            plate_number=plate,
            vendor_id=uuid.UUID(vendor_id) if vendor_id else None,
        )
        db.add(truck)
        await db.flush()  # populate truck.id without committing
        logger.info("Created new Truck record for plate %s", plate)
    else:
        # Backfill vendor_id if it was missing and schedule-service supplied one
        if truck.vendor_id is None and vendor_id:
            truck.vendor_id = uuid.UUID(vendor_id)
            await db.flush()

    return truck


async def process_alpr_entry_event(
    alpr_event: ALPREvent,
    db: AsyncSession,
    nats_js,
    schedule_service_url: str,
    http_client: httpx.AsyncClient,
    minio_client,
) -> None:
    """Handle an inbound ALPR entry event end-to-end.

    Steps:
    1. Persist the raw :class:`GateEvent`.
    2. Upsert the :class:`Truck` record.
    3. Evaluate arrival against Nagare schedule.
    4. Create a :class:`TruckMovement` with the outcome.
    5. Publish ``tms.gate.truck_arrived`` to JetStream.

    Args:
        alpr_event: Parsed ALPR event from the NATS message.
        db: Active async DB session (will be flushed; commit handled by caller).
        nats_js: JetStream context for publishing.
        schedule_service_url: Base URL of schedule-service.
        http_client: Shared HTTPX async client.
        minio_client: Boto3 MinIO client (available for future image archiving).
    """
    arrival_time = alpr_event.ts
    if arrival_time.tzinfo is None:
        arrival_time = arrival_time.replace(tzinfo=timezone.utc)

    # 1. Persist GateEvent
    gate_event = GateEvent(
        plate_number=alpr_event.plate,
        camera_id=alpr_event.camera_id,
        direction=alpr_event.direction,
        confidence=alpr_event.confidence,
        image_url=alpr_event.image_url,
        raw_payload=alpr_event.model_dump(mode="json"),
        detected_at=arrival_time,
    )
    db.add(gate_event)
    await db.flush()
    logger.debug("Saved GateEvent id=%s for plate %s", gate_event.id, alpr_event.plate)

    # 2. Evaluate against schedule
    result = await evaluate_truck_arrival(
        plate=alpr_event.plate,
        arrival_time=arrival_time,
        schedule_service_url=schedule_service_url,
        http_client=http_client,
    )

    action: str = result["action"]
    vendor_id_str: str | None = result.get("vendor_id")

    # 3. Upsert Truck record
    truck = await _get_or_create_truck(db, alpr_event.plate, vendor_id_str)

    # 4. Determine movement status from action
    status_map = {
        "allow": "proceeding",
        "hold": "waiting",
        "reject": "rejected",
    }
    movement_status = status_map.get(action, "waiting")

    # Parse consignment_id safely
    consignment_id: uuid.UUID | None = None
    raw_cid = result.get("consignment_id")
    if raw_cid:
        try:
            consignment_id = uuid.UUID(str(raw_cid))
        except (ValueError, AttributeError):
            logger.warning("Could not parse consignment_id: %s", raw_cid)

    # 5. Create TruckMovement
    movement = TruckMovement(
        truck_id=truck.id,
        consignment_id=consignment_id,
        plate_number=alpr_event.plate,
        gate_event_id=gate_event.id,
        status=movement_status,
        gate_in_at=arrival_time,
        nagare_slot_start=result.get("nagare_slot_start"),
        nagare_slot_end=result.get("nagare_slot_end"),
        minutes_to_slot=result.get("minutes_to_slot"),
        bay_code=result.get("bay_code"),
        rejection_reason=result.get("rejection_reason"),
    )
    db.add(movement)
    await db.flush()
    logger.info(
        "Created TruckMovement id=%s plate=%s status=%s",
        movement.id,
        alpr_event.plate,
        movement_status,
    )

    # 6. Publish tms.gate.truck_arrived
    arrived_event = TruckArrivedEvent(
        movement_id=movement.id,
        plate=alpr_event.plate,
        vendor_id=uuid.UUID(str(vendor_id_str)) if vendor_id_str else None,
        consignment_id=consignment_id,
        action=action,
        bay_code=result.get("bay_code"),
        minutes_to_slot=result.get("minutes_to_slot"),
        rejection_reason=result.get("rejection_reason"),
        arrived_at=arrival_time,
    )

    try:
        payload = arrived_event.model_dump_json().encode()
        await nats_js.publish("tms.gate.truck_arrived", payload)
        logger.info("Published tms.gate.truck_arrived for plate %s action=%s", alpr_event.plate, action)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to publish tms.gate.truck_arrived: %s", exc)


async def process_alpr_exit_event(
    alpr_event: ALPREvent,
    db: AsyncSession,
    nats_js,
) -> None:
    """Handle an inbound ALPR exit event.

    Steps:
    1. Persist the raw :class:`GateEvent`.
    2. Find the most recent active :class:`TruckMovement` for this plate.
    3. Mark it departed and record the departure timestamp.
    4. Publish ``tms.gate.truck_departed`` to JetStream.

    Args:
        alpr_event: Parsed ALPR exit event from the NATS message.
        db: Active async DB session.
        nats_js: JetStream context for publishing.
    """
    exit_time = alpr_event.ts
    if exit_time.tzinfo is None:
        exit_time = exit_time.replace(tzinfo=timezone.utc)

    # 1. Persist GateEvent
    gate_event = GateEvent(
        plate_number=alpr_event.plate,
        camera_id=alpr_event.camera_id,
        direction=alpr_event.direction,
        confidence=alpr_event.confidence,
        image_url=alpr_event.image_url,
        raw_payload=alpr_event.model_dump(mode="json"),
        detected_at=exit_time,
    )
    db.add(gate_event)
    await db.flush()

    # 2. Find the most recent non-departed movement for this plate
    result = await db.execute(
        select(TruckMovement)
        .where(
            TruckMovement.plate_number == alpr_event.plate,
            TruckMovement.status.notin_(["departed", "rejected"]),
        )
        .order_by(TruckMovement.created_at.desc())
        .limit(1)
    )
    movement = result.scalars().first()

    if movement is None:
        logger.warning(
            "Exit event for plate %s but no active movement found – creating stub record",
            alpr_event.plate,
        )
        # Still publish the departed event for downstream awareness
        departed_event = TruckDepartedEvent(
            movement_id=uuid.uuid4(),
            plate=alpr_event.plate,
            gate_out_at=exit_time,
        )
        try:
            await nats_js.publish(
                "tms.gate.truck_departed",
                departed_event.model_dump_json().encode(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to publish tms.gate.truck_departed (stub): %s", exc)
        return

    # 3. Update movement
    movement.status = "departed"
    movement.gate_out_at = exit_time
    await db.flush()
    logger.info("Marked TruckMovement %s as departed for plate %s", movement.id, alpr_event.plate)

    # 4. Publish tms.gate.truck_departed
    departed_event = TruckDepartedEvent(
        movement_id=movement.id,
        plate=alpr_event.plate,
        gate_out_at=exit_time,
    )
    try:
        await nats_js.publish(
            "tms.gate.truck_departed",
            departed_event.model_dump_json().encode(),
        )
        logger.info("Published tms.gate.truck_departed for plate %s", alpr_event.plate)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to publish tms.gate.truck_departed: %s", exc)
