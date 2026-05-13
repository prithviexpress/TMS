"""Truck self-registration service logic."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.vendor import TruckRegistrationRequest, TruckRegistrationResponse

logger = logging.getLogger(__name__)


async def register_truck(
    request: TruckRegistrationRequest,
    db: AsyncSession,
    nats_js,
    schedule_service_url: str,
    http_client: httpx.AsyncClient,
) -> TruckRegistrationResponse:
    """Register a truck plate and driver phone against a scheduled Nagare slot.

    Steps:
    1. PATCH the consignment in schedule-service to update truck_plate,
       driver_phone, and status → TRUCK_REGISTERED.
    2. Extract slot_start and bay_code from the response.
    3. Publish a ``tms.vendor.truck_registered`` event to NATS JetStream.
    4. Return a :class:`TruckRegistrationResponse` with a confirmation message.

    Args:
        request: Validated truck registration payload.
        db: Active async SQLAlchemy session (not directly used here but
            available for any future local persistence needs).
        nats_js: NATS JetStream context for publishing events.
        schedule_service_url: Base URL of the schedule-service.
        http_client: Shared :class:`httpx.AsyncClient` instance.

    Returns:
        :class:`TruckRegistrationResponse` with slot and bay details.

    Raises:
        :class:`httpx.HTTPStatusError` when schedule-service returns a
        non-2xx response.
    """
    # ── 1. Call schedule-service ───────────────────────────────────────────────
    patch_url = (
        f"{schedule_service_url}/api/v1/schedule/consignments/{request.consignment_id}"
    )
    payload = {
        "truck_plate": request.truck_plate,
        "driver_phone": request.driver_phone,
        "status": "TRUCK_REGISTERED",
    }

    logger.info(
        "Patching consignment %s at %s", request.consignment_id, patch_url
    )
    response = await http_client.patch(patch_url, json=payload)
    response.raise_for_status()

    data: dict = response.json()

    slot_start: datetime | None = None
    raw_slot = data.get("slot_start")
    if raw_slot:
        try:
            slot_start = datetime.fromisoformat(raw_slot)
        except ValueError:
            logger.warning("Could not parse slot_start %r from schedule-service", raw_slot)

    bay_code: str | None = data.get("bay_code")

    # ── 2. Publish NATS event ──────────────────────────────────────────────────
    event_payload = {
        "event": "tms.vendor.truck_registered",
        "consignment_id": str(request.consignment_id),
        "truck_plate": request.truck_plate,
        "driver_phone": request.driver_phone,
        "driver_name": request.driver_name,
        "slot_start": slot_start.isoformat() if slot_start else None,
        "bay_code": bay_code,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        await nats_js.publish(
            "tms.vendor.truck_registered",
            json.dumps(event_payload).encode(),
        )
        logger.info(
            "Published tms.vendor.truck_registered for consignment %s",
            request.consignment_id,
        )
    except Exception as exc:  # noqa: BLE001
        # Don't fail the registration if NATS publish fails; log and continue.
        logger.error(
            "Failed to publish truck_registered event for %s: %s",
            request.consignment_id,
            exc,
        )

    # ── 3. Return confirmation ─────────────────────────────────────────────────
    return TruckRegistrationResponse(
        consignment_id=request.consignment_id,
        truck_plate=request.truck_plate,
        driver_phone=request.driver_phone,
        slot_start=slot_start,
        bay_code=bay_code,
        message=(
            f"Truck {request.truck_plate} successfully registered for "
            f"consignment {request.consignment_id}."
        ),
    )
