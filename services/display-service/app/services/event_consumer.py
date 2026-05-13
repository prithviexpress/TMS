"""NATS JetStream event consumer for display-service.

Subscribes to TMS gate and bay events and translates them into hardware
commands for LED display panels and Banner K70 bay lights.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
import nats
import nats.js
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.k70_state import K70LightState
from app.services.k70_client import set_k70_light
from app.services.led_client import send_led_message
from tms_shared.models.events import BayOccupiedEvent, BayVacatedEvent, TruckArrivedEvent

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_led_payload(line1: str, line2: str = "", line3: str = "", color: str = "GREEN") -> dict:
    """Build the JSON payload for an LED display panel."""
    return {
        "Line_1": line1[:20],
        "Line_2": line2[:20],
        "Line_3": line3[:20],
        "Color": color,
    }


async def _get_led_display(display_code: str) -> tuple[str, str]:
    """Return (ip_address, endpoint_path) for the given display_code.

    Falls back to the settings IP if no DB row exists for the code.
    """
    from sqlalchemy import select

    from app.models.led_display import LEDDisplay

    settings = get_settings()
    fallback_ip = {
        "GATE_2_ENTRY": settings.LED_DISPLAY_GATE2_IP,
        "PARKING_EXIT": settings.LED_DISPLAY_PARKING_EXIT_IP,
    }.get(display_code, settings.LED_DISPLAY_GATE2_IP)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LEDDisplay).where(
                LEDDisplay.display_code == display_code,
                LEDDisplay.is_active.is_(True),
            )
        )
        display = result.scalar_one_or_none()

    if display:
        return display.ip_address, display.endpoint_path
    return fallback_ip, "/spi/screen/message"


async def _upsert_k70_state(
    db: AsyncSession,
    bay_id: uuid.UUID,
    bay_code: str,
    color: str | None,
    mode: str | None,
    light_address: str | None,
) -> None:
    """Insert or update the K70 light state row for this bay."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(K70LightState).values(
        bay_id=bay_id,
        bay_code=bay_code,
        color=color,
        mode=mode,
        light_address=light_address,
        updated_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_update(
        index_elements=["bay_id"],
        set_={
            "color": color,
            "mode": mode,
            "light_address": light_address,
            "updated_at": datetime.now(tz=timezone.utc),
        },
    )
    await db.execute(stmt)
    await db.commit()


# ── Event handlers ────────────────────────────────────────────────────────────


async def _handle_truck_arrived(
    event: TruckArrivedEvent,
    http_client: httpx.AsyncClient,
) -> None:
    settings = get_settings()
    ip, path = await _get_led_display("GATE_2_ENTRY")

    if event.action == "allow" and event.bay_code:
        payload = _build_led_payload(
            line1="PROCEED TO BAY",
            line2=event.bay_code,
            line3="",
            color="GREEN",
        )
        subject = "tms.gate.truck_arrived"
        async with AsyncSessionLocal() as db:
            await send_led_message(
                http_client, ip, path, payload,
                db=db, device_id="GATE_2_ENTRY", trigger_event=subject,
            )
            # Turn K70 GREEN SOLID for the assigned bay — we don't have
            # bay_id here so we log only; bay-service sends tms.bay.occupied.
            logger.info(
                "Truck %s allowed → bay %s; LED updated", event.plate, event.bay_code
            )

    elif event.action == "hold":
        payload = _build_led_payload(
            line1="WAIT IN",
            line2="PARKING AREA",
            color="AMBER",
        )
        async with AsyncSessionLocal() as db:
            await send_led_message(
                http_client, ip, path, payload,
                db=db, device_id="GATE_2_ENTRY",
                trigger_event="tms.gate.truck_arrived",
            )

    elif event.action == "reject":
        payload = _build_led_payload(
            line1="MUMBAI TRIP",
            line2="CONTACT SECURITY",
            color="RED",
        )
        async with AsyncSessionLocal() as db:
            await send_led_message(
                http_client, ip, path, payload,
                db=db, device_id="GATE_2_ENTRY",
                trigger_event="tms.gate.truck_arrived",
            )


async def _handle_bay_occupied(
    event: BayOccupiedEvent,
    http_client: httpx.AsyncClient,
) -> None:
    """K70 → GREEN FLASH (truck is unloading)."""
    settings = get_settings()
    light_address = f"bay-{event.bay_code}"

    code, body = await set_k70_light(
        http_client,
        gateway_ip=settings.K70_GATEWAY_IP,
        light_address=light_address,
        color="GREEN",
        mode="FLASH",
        trigger_event="tms.bay.occupied",
    )

    async with AsyncSessionLocal() as db:
        await _upsert_k70_state(
            db,
            bay_id=event.bay_id,
            bay_code=event.bay_code,
            color="GREEN",
            mode="FLASH",
            light_address=light_address,
        )

    logger.info("Bay %s occupied → K70 GREEN FLASH (HTTP %s)", event.bay_code, code)


async def _handle_bay_vacated(
    event: BayVacatedEvent,
    http_client: httpx.AsyncClient,
) -> None:
    """K70 → OFF (bay is free)."""
    settings = get_settings()
    light_address = f"bay-{event.bay_code}"

    code, body = await set_k70_light(
        http_client,
        gateway_ip=settings.K70_GATEWAY_IP,
        light_address=light_address,
        color="OFF",
        mode="SOLID",
        trigger_event="tms.bay.vacated",
    )

    async with AsyncSessionLocal() as db:
        await _upsert_k70_state(
            db,
            bay_id=event.bay_id,
            bay_code=event.bay_code,
            color="OFF",
            mode="SOLID",
            light_address=light_address,
        )

    logger.info("Bay %s vacated → K70 OFF (HTTP %s)", event.bay_code, code)


# ── Subscriber setup ──────────────────────────────────────────────────────────


async def start_event_consumer(nc: nats.NATS, http_client: httpx.AsyncClient) -> None:
    """Register JetStream push subscribers for all relevant TMS subjects.

    Args:
        nc: Active NATS client connection.
        http_client: Shared HTTP client to forward hardware commands.
    """
    js = nc.jetstream()

    async def on_truck_arrived(msg: nats.aio.client.Msg) -> None:
        try:
            data = json.loads(msg.data.decode())
            event = TruckArrivedEvent(**data)
            await _handle_truck_arrived(event, http_client)
        except Exception:
            logger.exception("Error handling tms.gate.truck_arrived: %s", msg.data)
        finally:
            await msg.ack()

    async def on_bay_occupied(msg: nats.aio.client.Msg) -> None:
        try:
            data = json.loads(msg.data.decode())
            event = BayOccupiedEvent(**data)
            await _handle_bay_occupied(event, http_client)
        except Exception:
            logger.exception("Error handling tms.bay.occupied: %s", msg.data)
        finally:
            await msg.ack()

    async def on_bay_vacated(msg: nats.aio.client.Msg) -> None:
        try:
            data = json.loads(msg.data.decode())
            event = BayVacatedEvent(**data)
            await _handle_bay_vacated(event, http_client)
        except Exception:
            logger.exception("Error handling tms.bay.vacated: %s", msg.data)
        finally:
            await msg.ack()

    # JetStream durable push subscriptions
    await js.subscribe(
        "tms.gate.truck_arrived",
        durable="display-gate-truck-arrived",
        cb=on_truck_arrived,
        manual_ack=True,
    )
    await js.subscribe(
        "tms.bay.occupied",
        durable="display-bay-occupied",
        cb=on_bay_occupied,
        manual_ack=True,
    )
    await js.subscribe(
        "tms.bay.vacated",
        durable="display-bay-vacated",
        cb=on_bay_vacated,
        manual_ack=True,
    )

    logger.info("Display-service NATS consumers started")
