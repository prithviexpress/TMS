"""Tests for display-service: LED client, K70 client, and health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


# ── LED client tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_led_message_success():
    """LED client returns status 200 and response body on success."""
    from app.services.led_client import send_led_message

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    payload = {"Line_1": "PROCEED TO BAY", "Line_2": "AR-N1", "Line_3": "", "Color": "GREEN"}
    code, body = await send_led_message(
        http_client=mock_client,
        ip_address="192.168.10.51",
        endpoint_path="/spi/screen/message",
        payload=payload,
    )

    assert code == 200
    assert body == "OK"
    mock_client.post.assert_awaited_once_with(
        "http://192.168.10.51/spi/screen/message",
        json=payload,
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_send_led_message_timeout():
    """LED client returns 408 on timeout and does not raise."""
    from app.services.led_client import send_led_message

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("timed out")

    code, body = await send_led_message(
        http_client=mock_client,
        ip_address="192.168.10.51",
        endpoint_path="/spi/screen/message",
        payload={"Line_1": "TEST"},
    )

    assert code == 408
    assert "timed out" in body.lower()


@pytest.mark.asyncio
async def test_send_led_message_connection_error():
    """LED client returns 503 on connection error."""
    from app.services.led_client import send_led_message

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("connection refused")

    code, body = await send_led_message(
        http_client=mock_client,
        ip_address="192.168.10.51",
        endpoint_path="/spi/screen/message",
        payload={"Line_1": "TEST"},
    )

    assert code == 503


# ── K70 client tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_k70_light_success():
    """K70 client sends the correct lower-case color/mode and returns 200."""
    from app.services.k70_client import set_k70_light

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"status":"ok"}'

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    code, body = await set_k70_light(
        http_client=mock_client,
        gateway_ip="192.168.10.50",
        light_address="bay-AR-N1",
        color="GREEN",
        mode="SOLID",
    )

    assert code == 200
    mock_client.post.assert_awaited_once_with(
        "http://192.168.10.50/api/lights/bay-AR-N1/state",
        json={"color": "green", "mode": "solid"},
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_set_k70_light_timeout():
    """K70 client returns 408 on gateway timeout."""
    from app.services.k70_client import set_k70_light

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("timed out")

    code, body = await set_k70_light(
        http_client=mock_client,
        gateway_ip="192.168.10.50",
        light_address="bay-AR-N1",
        color="OFF",
        mode="SOLID",
    )

    assert code == 408


@pytest.mark.asyncio
async def test_set_k70_light_off():
    """K70 client sends color=off to turn the light off."""
    from app.services.k70_client import set_k70_light

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "accepted"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await set_k70_light(
        http_client=mock_client,
        gateway_ip="192.168.10.50",
        light_address="bay-B2",
        color="OFF",
        mode="SOLID",
    )

    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["json"]["color"] == "off"


# ── Health endpoint test ──────────────────────────────────────────────────────


def test_health_endpoint():
    """GET /api/v1/display/health returns {status: ok} without DB or NATS."""
    # Import the router directly and build a minimal app to avoid the full lifespan
    from fastapi import FastAPI
    from app.routers.lights import router

    test_app = FastAPI()
    test_app.include_router(router)

    with TestClient(test_app) as client:
        response = client.get("/api/v1/display/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
