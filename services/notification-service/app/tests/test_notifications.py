import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from app.main import app


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/notifications/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_render_template():
    from jinja2 import Environment, BaseLoader
    env = Environment(loader=BaseLoader())
    body = "Truck {{truck_plate}} proceed to {{bay_code}}. - MSIL TMS"
    rendered = env.from_string(body).render(truck_plate="KA01AB1234", bay_code="AR-N1")
    assert "KA01AB1234" in rendered
    assert "AR-N1" in rendered


@pytest.mark.asyncio
async def test_send_sms_dev_mode():
    from unittest.mock import MagicMock
    import httpx
    client = httpx.AsyncClient()
    from app.services.sms_provider import send_sms_msg91
    msg_id, status = await send_sms_msg91(client, "", "MSILTM", "9999999999", "Test message")
    assert status == "SENT"
    assert msg_id == "dev-mock-id"
    await client.aclose()
