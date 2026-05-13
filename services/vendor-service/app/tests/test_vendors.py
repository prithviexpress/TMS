"""Tests for vendor-service API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.vendor import Base

# ── In-memory SQLite engine for tests ─────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session():
    """Yield a transactional async session backed by in-memory SQLite."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def mock_nats_js():
    js = AsyncMock()
    js.publish = AsyncMock(return_value=None)
    return js


@pytest.fixture
def mock_http_client():
    return AsyncMock(spec=AsyncClient)


@pytest.fixture
def test_client(db_session, mock_nats_js, mock_http_client):
    """Return a synchronous TestClient with overridden dependencies."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.nats_js = mock_nats_js
    app.state.http_client = mock_http_client

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()


# ── Health ─────────────────────────────────────────────────────────────────────


def test_health(test_client):
    resp = test_client.get("/api/v1/vendors/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Create vendor ──────────────────────────────────────────────────────────────


def test_create_vendor(test_client):
    """POST /api/v1/vendors creates a vendor profile and returns 201."""
    payload = {
        "vendor_code": "V001",
        "name": "Acme Logistics",
        "contact_name": "Ravi Kumar",
        "contact_phone": "+919876543210",
        "whatsapp_number": "+919876543210",
        "email": "ravi@acme.in",
        "city": "Pune",
    }

    # Auth is validated via tms_shared.auth.verify_token; patch it out
    with patch("tms_shared.auth.verify_token", return_value={"sub": str(uuid.uuid4())}):
        resp = test_client.post(
            "/api/v1/vendors",
            json=payload,
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["vendor_code"] == "V001"
    assert data["name"] == "Acme Logistics"
    assert data["city"] == "Pune"
    assert data["is_active"] is True
    # A registration_token should have been auto-generated
    assert data["registration_token"] is not None
    assert len(data["registration_token"]) == 36  # UUID format


def test_create_vendor_duplicate_code(test_client):
    """Creating two vendors with the same vendor_code returns 409."""
    payload = {"vendor_code": "V002", "name": "Duplicate Corp"}

    with patch("tms_shared.auth.verify_token", return_value={"sub": str(uuid.uuid4())}):
        resp1 = test_client.post(
            "/api/v1/vendors",
            json=payload,
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp1.status_code == 201

        resp2 = test_client.post(
            "/api/v1/vendors",
            json=payload,
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp2.status_code == 409


# ── Register truck ─────────────────────────────────────────────────────────────


def test_register_truck(test_client, mock_http_client):
    """POST /api/v1/vendors/register-truck calls schedule-service and returns confirmation."""
    consignment_id = uuid.uuid4()
    slot_start = datetime.now(tz=timezone.utc).isoformat()
    bay_code = "BAY-03"

    # Mock schedule-service PATCH response
    mock_http_client.patch = AsyncMock(
        return_value=Response(
            200,
            json={
                "id": str(consignment_id),
                "truck_plate": "MH12AB1234",
                "driver_phone": "+919999999999",
                "status": "TRUCK_REGISTERED",
                "slot_start": slot_start,
                "bay_code": bay_code,
            },
        )
    )

    payload = {
        "consignment_id": str(consignment_id),
        "truck_plate": "MH12AB1234",
        "driver_name": "Suresh Patil",
        "driver_phone": "+919999999999",
    }

    with patch("tms_shared.auth.verify_token", return_value={"sub": str(uuid.uuid4())}):
        resp = test_client.post(
            "/api/v1/vendors/register-truck",
            json=payload,
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["truck_plate"] == "MH12AB1234"
    assert data["driver_phone"] == "+919999999999"
    assert data["bay_code"] == bay_code
    assert "successfully registered" in data["message"]


def test_register_truck_schedule_service_error(test_client, mock_http_client):
    """If schedule-service returns 404, the endpoint returns 404."""
    consignment_id = uuid.uuid4()

    mock_http_client.patch = AsyncMock(
        return_value=Response(404, json={"detail": "Consignment not found"})
    )

    payload = {
        "consignment_id": str(consignment_id),
        "truck_plate": "MH12ZZ9999",
        "driver_phone": "+910000000000",
    }

    with patch("tms_shared.auth.verify_token", return_value={"sub": str(uuid.uuid4())}):
        resp = test_client.post(
            "/api/v1/vendors/register-truck",
            json=payload,
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 404
