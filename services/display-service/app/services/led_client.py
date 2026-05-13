"""HTTP client for LED display panels.

Each panel exposes a simple REST endpoint at ``POST /spi/screen/message``
that accepts a JSON body describing what text and colour to show.
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


async def send_led_message(
    http_client: httpx.AsyncClient,
    ip_address: str,
    endpoint_path: str,
    payload: dict,
    db: AsyncSession | None = None,
    device_id: str | None = None,
    trigger_event: str | None = None,
) -> tuple[int, str]:
    """POST a message payload to an LED display panel.

    Args:
        http_client: Shared :class:`httpx.AsyncClient` instance.
        ip_address: IP address of the LED panel on the plant network.
        endpoint_path: URL path on the panel firmware (default ``/spi/screen/message``).
        payload: JSON-serialisable dict with ``Line_1``, ``Line_2``, etc.
        db: Optional async DB session for writing to ``display_commands_log``.
        device_id: Human-readable device identifier stored in the log row.
        trigger_event: NATS subject that triggered this command (for audit).

    Returns:
        A ``(status_code, response_body)`` tuple.
    """
    url = f"http://{ip_address}{endpoint_path}"
    sent_at = datetime.now(tz=timezone.utc)
    status_code = 0
    response_body = ""

    try:
        response = await http_client.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
        status_code = response.status_code
        response_body = response.text
        logger.info(
            "LED command sent to %s → HTTP %s", url, status_code
        )
    except httpx.TimeoutException:
        status_code = 408
        response_body = "Request timed out"
        logger.warning("LED panel at %s timed out", url)
    except httpx.RequestError as exc:
        status_code = 503
        response_body = str(exc)
        logger.error("LED panel at %s unreachable: %s", url, exc)

    if db is not None:
        log_entry = DisplayCommandLog(
            id=uuid.uuid4(),
            device_type="LED",
            device_id=device_id or ip_address,
            command_payload=payload,
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
            logger.exception("Failed to persist LED command log")

    return status_code, response_body
