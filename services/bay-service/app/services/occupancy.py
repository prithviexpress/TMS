"""Core bay state machine — processes sensor updates and manual assignments.

State transitions:
    VACANT  → OCCUPIED  (sensor detects truck OR manual assign)
    OCCUPIED → VACANT   (sensor clears OR manual release)
    VACANT  → RESERVED  (gate-service assigns a bay ahead of truck arrival)
    RESERVED → OCCUPIED (truck actually docks)
    RESERVED → VACANT   (truck did not arrive / was rerouted)

NATS events published:
    tms.bay.occupied       — BayOccupiedEvent
    tms.bay.vacated        — BayVacatedEvent
    tms.bay.sensor_conflict — BaySensorConflictEvent
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from nats.aio.client import Client as NATSClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.cache import set_bay_status
from app.models.bay import Bay
from app.models.bay_occupancy import BayOccupancy
from app.models.bay_occupancy_history import BayOccupancyHistory
from app.models.sensor_reading import SensorReading
from tms_shared.models.events import (
    BayOccupiedEvent,
    BaySensorConflictEvent,
    BayVacatedEvent,
)

logger = logging.getLogger(__name__)

# NATS subjects
_SUBJECT_OCCUPIED = "tms.bay.occupied"
_SUBJECT_VACATED = "tms.bay.vacated"
_SUBJECT_CONFLICT = "tms.bay.sensor_conflict"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_status_dict(bay: Bay, occ: BayOccupancy) -> dict:
    """Build the Redis-cached status dict for a bay."""
    time_left: int | None = None
    if occ.expected_release_at and occ.occupied_at:
        delta = occ.expected_release_at - _now()
        time_left = max(0, int(delta.total_seconds() / 60))

    return {
        "bay_id": str(bay.id),
        "bay_code": bay.bay_code,
        "zone": bay.zone,
        "status": occ.status,
        "movement_id": str(occ.movement_id) if occ.movement_id else None,
        "vendor_id": str(occ.vendor_id) if occ.vendor_id else None,
        "vendor_name": occ.vendor_name,
        "truck_plate": occ.truck_plate,
        "occupied_at": occ.occupied_at.isoformat() if occ.occupied_at else None,
        "expected_release_at": occ.expected_release_at.isoformat() if occ.expected_release_at else None,
        "time_left_minutes": time_left,
        "updated_at": occ.updated_at.isoformat(),
    }


async def _publish(nc: NATSClient, subject: str, payload: dict) -> None:
    """Serialise *payload* to JSON and publish on *subject*."""
    try:
        js = nc.jetstream()
        await js.publish(subject, json.dumps(payload, default=str).encode())
        logger.debug("Published NATS event %s", subject)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to publish NATS event %s: %s", subject, exc)


async def _control_light(
    http_client: httpx.AsyncClient,
    display_service_url: str,
    bay: Bay,
    color: str,
) -> None:
    """Send a light-color command to display-service for the K70 indicator."""
    if not bay.light_address:
        return
    try:
        url = f"{display_service_url.rstrip('/')}/api/v1/display/k70/set"
        await http_client.post(
            url,
            json={
                "light_address": bay.light_address,
                "gateway_ip": bay.light_gateway_ip,
                "color": color,
            },
            timeout=2.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("display-service light control failed for bay %s: %s", bay.bay_code, exc)


async def _get_or_create_occupancy(db: AsyncSession, bay: Bay) -> BayOccupancy:
    """Fetch the existing BayOccupancy row or create a VACANT default."""
    result = await db.execute(
        select(BayOccupancy).where(BayOccupancy.bay_id == bay.id)
    )
    occ = result.scalar_one_or_none()
    if occ is None:
        occ = BayOccupancy(
            id=uuid4(),
            bay_id=bay.id,
            status="VACANT",
            updated_at=_now(),
        )
        db.add(occ)
        await db.flush()
    return occ


async def _open_history(db: AsyncSession, bay: Bay, occ: BayOccupancy) -> None:
    """Insert a new BayOccupancyHistory row when a bay becomes OCCUPIED."""
    history = BayOccupancyHistory(
        id=uuid4(),
        bay_id=bay.id,
        bay_code=bay.bay_code,
        movement_id=occ.movement_id,
        vendor_name=occ.vendor_name,
        truck_plate=occ.truck_plate,
        status="OCCUPIED",
        started_at=occ.occupied_at or _now(),
    )
    db.add(history)
    await db.flush()


async def _close_history(db: AsyncSession, bay: Bay, ended_at: datetime) -> None:
    """Close the most recent open BayOccupancyHistory row for *bay*."""
    result = await db.execute(
        select(BayOccupancyHistory)
        .where(
            BayOccupancyHistory.bay_id == bay.id,
            BayOccupancyHistory.ended_at.is_(None),
        )
        .order_by(BayOccupancyHistory.started_at.desc())
        .limit(1)
    )
    history = result.scalar_one_or_none()
    if history is None:
        return
    history.ended_at = ended_at
    delta = ended_at - history.started_at
    history.duration_minutes = max(0, int(delta.total_seconds() / 60))
    await db.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_sensor_update(
    db: AsyncSession,
    redis: aioredis.Redis,
    nc: NATSClient,
    bay: Bay,
    occupied: bool,
    distance_mm: int | None,
    device_eui: str,
    display_service_url: str,
) -> None:
    """Core state machine — triggered by a LoRaWAN sensor reading.

    Steps:
        1. Write ``sensor_reading`` record.
        2. Fetch current ``bay_occupancy`` record.
        3. If occupied state changed → transition the state machine.
        4. Update Redis cache.
        5. Publish NATS event.
        6. Send K70 light color command to display-service.
        7. Detect ghost occupancy (sensor occupied but no movement_id).
    """
    now = _now()

    # 1. Persist raw sensor reading
    reading = SensorReading(
        id=uuid4(),
        device_eui=device_eui,
        bay_id=bay.id,
        occupied=occupied,
        distance_mm=distance_mm,
        raw_payload={},  # caller may enrich this; kept minimal here
        received_at=now,
        created_at=now,
    )
    db.add(reading)

    # 2. Get current occupancy state
    occ = await _get_or_create_occupancy(db, bay)
    previous_status = occ.status

    # Map "occupied" bool → target status (RESERVED stays RESERVED if sensor sees it)
    if occupied:
        target_status = "OCCUPIED"
    else:
        target_status = "VACANT"

    state_changed = (
        (occupied and previous_status != "OCCUPIED")
        or (not occupied and previous_status not in ("VACANT",))
    )

    if state_changed:
        logger.info(
            "Bay %s: %s → %s (sensor eui=%s dist=%s)",
            bay.bay_code,
            previous_status,
            target_status,
            device_eui,
            distance_mm,
        )
        occ.status = target_status
        occ.updated_at = now

        async with httpx.AsyncClient() as http_client:
            if target_status == "OCCUPIED":
                # 3b. Transition → OCCUPIED
                occ.occupied_at = now
                await _open_history(db, bay, occ)
                await db.commit()

                # 4. Cache
                await set_bay_status(redis, bay.bay_code, _build_status_dict(bay, occ))

                # 5. NATS
                event = BayOccupiedEvent(
                    bay_id=bay.id,
                    bay_code=bay.bay_code,
                    movement_id=occ.movement_id,
                    truck_plate=occ.truck_plate,
                    vendor_id=occ.vendor_id,
                    vendor_name=occ.vendor_name,
                    occupied_at=now,
                )
                await _publish(nc, _SUBJECT_OCCUPIED, event.model_dump())

                # 6. Light → RED (occupied)
                await _control_light(http_client, display_service_url, bay, "RED")

                # 7. Conflict: sensor sees truck but no movement linked
                if occ.movement_id is None:
                    conflict = BaySensorConflictEvent(
                        bay_id=bay.id,
                        bay_code=bay.bay_code,
                        device_eui=device_eui,
                        detected_at=now,
                    )
                    await _publish(nc, _SUBJECT_CONFLICT, conflict.model_dump())

            else:
                # 3c. Transition → VACANT
                vacated_at = now
                occ.movement_id = None
                occ.vendor_id = None
                occ.vendor_name = None
                occ.truck_plate = None
                occ.occupied_at = None
                occ.expected_release_at = None

                await _close_history(db, bay, vacated_at)
                await db.commit()

                # 4. Cache
                await set_bay_status(redis, bay.bay_code, _build_status_dict(bay, occ))

                # 5. NATS
                event = BayVacatedEvent(
                    bay_id=bay.id,
                    bay_code=bay.bay_code,
                    movement_id=None,
                    duration_minutes=None,
                    vacated_at=vacated_at,
                )
                await _publish(nc, _SUBJECT_VACATED, event.model_dump())

                # 6. Light → GREEN (vacant)
                await _control_light(http_client, display_service_url, bay, "GREEN")
    else:
        # No state change — still refresh cache TTL and commit sensor reading
        await db.commit()
        await set_bay_status(redis, bay.bay_code, _build_status_dict(bay, occ))

    logger.debug("process_sensor_update complete for bay %s", bay.bay_code)


async def assign_bay(
    db: AsyncSession,
    redis: aioredis.Redis,
    nc: NATSClient,
    bay: Bay,
    movement_id: UUID,
    vendor_id: UUID | None,
    vendor_name: str | None,
    truck_plate: str | None,
    expected_release_at: datetime | None,
    display_service_url: str,
    status: str = "RESERVED",
) -> BayOccupancy:
    """Manually assign a truck movement to a bay (RESERVED or OCCUPIED).

    Called by:
    - The REST PATCH /assign endpoint (Mendix operators).
    - The NATS event consumer when a gate-service ``tms.gate.truck_arrived``
      event with action=allow arrives.
    """
    now = _now()
    occ = await _get_or_create_occupancy(db, bay)

    occ.status = status
    occ.movement_id = movement_id
    occ.vendor_id = vendor_id
    occ.vendor_name = vendor_name
    occ.truck_plate = truck_plate
    occ.expected_release_at = expected_release_at
    occ.updated_at = now

    if status == "OCCUPIED" and occ.occupied_at is None:
        occ.occupied_at = now
        await _open_history(db, bay, occ)

    await db.commit()
    await db.refresh(occ)

    await set_bay_status(redis, bay.bay_code, _build_status_dict(bay, occ))

    if status == "OCCUPIED":
        event = BayOccupiedEvent(
            bay_id=bay.id,
            bay_code=bay.bay_code,
            movement_id=occ.movement_id,
            truck_plate=occ.truck_plate,
            vendor_id=occ.vendor_id,
            vendor_name=occ.vendor_name,
            occupied_at=now,
        )
        await _publish(nc, _SUBJECT_OCCUPIED, event.model_dump())
        async with httpx.AsyncClient() as http_client:
            await _control_light(http_client, display_service_url, bay, "RED")

    return occ


async def release_bay(
    db: AsyncSession,
    redis: aioredis.Redis,
    nc: NATSClient,
    bay: Bay,
    display_service_url: str,
) -> BayOccupancy:
    """Manually release a bay → VACANT."""
    now = _now()
    occ = await _get_or_create_occupancy(db, bay)

    previous_movement_id = occ.movement_id
    await _close_history(db, bay, now)

    occ.status = "VACANT"
    occ.movement_id = None
    occ.vendor_id = None
    occ.vendor_name = None
    occ.truck_plate = None
    occ.occupied_at = None
    occ.expected_release_at = None
    occ.updated_at = now

    await db.commit()
    await db.refresh(occ)

    await set_bay_status(redis, bay.bay_code, _build_status_dict(bay, occ))

    event = BayVacatedEvent(
        bay_id=bay.id,
        bay_code=bay.bay_code,
        movement_id=previous_movement_id,
        duration_minutes=None,
        vacated_at=now,
    )
    await _publish(nc, _SUBJECT_VACATED, event.model_dump())

    async with httpx.AsyncClient() as http_client:
        await _control_light(http_client, display_service_url, bay, "GREEN")

    return occ
