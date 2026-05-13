"""HTTP client for Banner K70 bay indicator lights via wireless gateway.

The gateway exposes a REST API at ``POST /api/lights/{light_address}/state``
that sets the colour and mode for a specific bay light fixture.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.led_display import DisplayCommandLog

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


async def set_k70_light(
    http_client: httpx.AsyncClient,
    gateway_ip: str,
    light_address: str,
    color: str,
    mode: str,
    db: AsyncSession | None = None,
    trigger_event: str | None = None,
) -> tuple[int, str]:
    """Set the colour and mode of a Banner K70 bay light via the wireless gateway.

    Args:
        http_client: Shared :class:`httpx.AsyncClient` instance.
        gateway_ip: IP address of the K70 wireless gateway (e.g. ``192.168.10.50``).
        light_address: Fixture identifier known to the gateway (e.g. ``"bay-A1"``).
        color: One of ``GREEN``, ``RED``, ``AMBER``, ``OFF`` (sent lower-case to gateway).
        mode: One of ``SOLID``, ``FLASH`` (sent lower-case to gateway).
        db: Optional async DB session for audit logging.
        trigger_event: NATS subject that triggered this command.

    Returns:
        A ``(status_code, response_body)`` tuple.
    """
    url = f"http://{gateway_ip}/api/lights/{light_address}/state"
    body = {"color": color.lower(), "mode": mode.lower()}
    sent_at = datetime.now(tz=timezone.utc)
    status_code = 0
    response_body = ""

    try:
        response = await http_client.post(url, json=body, timeout=_TIMEOUT_SECONDS)
        status_code = response.status_code
        response_body = response.text
        logger.info(
            "K70 command sent to %s (color=%s mode=%s) → HTTP %s",
            url, color, mode, status_code,
        )
    except httpx.TimeoutException:
        status_code = 408
        response_body = "Request timed out"
        logger.warning("K70 gateway at %s timed out (address=%s)", gateway_ip, light_address)
    except httpx.RequestError as exc:
        status_code = 503
        response_body = str(exc)
        logger.error("K70 gateway at %s unreachable: %s", gateway_ip, exc)

    if db is not None:
        log_entry = DisplayCommandLog(
            id=uuid.uuid4(),
            device_type="K70_LIGHT",
            device_id=light_address,
            command_payload=body,
            trigger_event=trigger_event,
            response_code=status_code,
            response_body=response_body[:4096] if response_body else None,
            sent_at=sent_at,
        )
        db.add(log_entry)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Failed to persist K70 command log")

    return status_code, response_body
