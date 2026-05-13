"""LED display panel router.

Provides HTTP endpoints to send messages to individual LED panels and
query their current configuration.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.led_display import LEDDisplay
from app.schemas.display import LEDMessageRequest, LEDStatusResponse
from app.services.led_client import send_led_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/display/led", tags=["LED Displays"])


def _get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.post("/{display_id}/message", status_code=status.HTTP_200_OK)
async def post_led_message(
    display_id: uuid.UUID,
    body: LEDMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a text message to a specific LED display panel.

    Looks up the panel by its UUID, then POSTs the message payload directly
    to the panel's firmware endpoint.
    """
    result = await db.execute(
        select(LEDDisplay).where(LEDDisplay.id == display_id)
    )
    display = result.scalar_one_or_none()
    if display is None:
        raise HTTPException(status_code=404, detail="LED display not found")
    if not display.is_active:
        raise HTTPException(status_code=409, detail="LED display is not active")

    http_client = _get_http_client(request)
    payload = body.model_dump()

    code, resp_body = await send_led_message(
        http_client=http_client,
        ip_address=display.ip_address,
        endpoint_path=display.endpoint_path,
        payload=payload,
        db=db,
        device_id=display.display_code,
        trigger_event="manual_api",
    )

    return {
        "display_id": str(display_id),
        "display_code": display.display_code,
        "status_code": code,
        "response": resp_body,
    }


@router.get("/{display_id}/status", response_model=LEDStatusResponse)
async def get_led_status(
    display_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> LEDStatusResponse:
    """Return the current configuration/status of an LED display panel."""
    result = await db.execute(
        select(LEDDisplay).where(LEDDisplay.id == display_id)
    )
    display = result.scalar_one_or_none()
    if display is None:
        raise HTTPException(status_code=404, detail="LED display not found")

    return LEDStatusResponse(
        display_id=display.id,
        display_code=display.display_code,
        ip_address=display.ip_address,
        endpoint_path=display.endpoint_path,
        is_active=display.is_active,
    )
