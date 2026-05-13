"""Sensor ingest endpoint — receives Chirpstack LoRaWAN webhooks.

Route
-----
POST /api/v1/bays/sensor/ingest

Security: validated via ``X-API-Key`` header (shared secret).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.cache import get_bay_status, get_redis
from app.config import settings
from app.database import get_db
from app.models.bay import Bay
from app.models.sensor_reading import SensorReading
from app.routers.bays import broadcast_bay_event
from app.schemas.sensor_ingest import ChirpstackPayload
from app.services.occupancy import process_sensor_update
from app.services.sensor_decoder import decode_chirpstack_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bays/sensor", tags=["sensor"])


async def _validate_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Dependency: reject requests with a wrong LoRaWAN ingest API key."""
    if x_api_key != settings.LORAWAN_INGEST_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


@router.post(
    "/ingest",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_validate_api_key)],
)
async def ingest_sensor(
    payload: ChirpstackPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Handle a Chirpstack HTTP integration uplink webhook.

    1. Decode the Chirpstack payload.
    2. Lookup the bay by DevEUI.
    3. If bay found → run the occupancy state machine.
    4. If bay not found → store an unmatched sensor_reading for audit.
    5. Broadcast any state change to SSE subscribers.
    """
    raw_dict = payload.model_dump(mode="python")

    try:
        device_eui, occupied, distance_mm, temperature_c = decode_chirpstack_payload(raw_dict)
    except ValueError as exc:
        logger.error("Failed to decode Chirpstack payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "Sensor ingest: eui=%s occupied=%s dist_mm=%s temp_c=%s",
        device_eui,
        occupied,
        distance_mm,
        temperature_c,
    )

    # Lookup bay by DevEUI
    result = await db.execute(
        select(Bay).where(Bay.sensor_device_eui == device_eui, Bay.is_active.is_(True))
    )
    bay = result.scalar_one_or_none()

    nc = request.app.state.nats_client

    if bay is None:
        logger.warning("Sensor DevEUI %s not registered to any active bay — storing orphan reading", device_eui)
        # Store an orphaned reading for debugging / commissioning
        reading = SensorReading(
            id=uuid4(),
            device_eui=device_eui,
            bay_id=None,
            occupied=occupied,
            distance_mm=distance_mm,
            temperature_c=temperature_c,
            raw_payload=raw_dict,
            received_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(reading)
        await db.commit()
        return  # 204

    # Run the core state machine
    await process_sensor_update(
        db=db,
        redis=redis,
        nc=nc,
        bay=bay,
        occupied=occupied,
        distance_mm=distance_mm,
        device_eui=device_eui,
        display_service_url=settings.DISPLAY_SERVICE_URL,
    )

    # Also store the temperature on the reading (process_sensor_update stores it separately)
    # and persist the full raw_payload
    result2 = await db.execute(
        select(SensorReading)
        .where(SensorReading.device_eui == device_eui, SensorReading.bay_id == bay.id)
        .order_by(SensorReading.received_at.desc())
        .limit(1)
    )
    last_reading = result2.scalar_one_or_none()
    if last_reading and last_reading.raw_payload == {}:
        last_reading.raw_payload = raw_dict
        last_reading.temperature_c = temperature_c
        await db.commit()

    # Push SSE update
    cached = await get_bay_status(redis, bay.bay_code)
    if cached:
        await broadcast_bay_event(cached)
