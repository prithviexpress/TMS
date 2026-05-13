"""Tests for consignment, gantt, and gate-check endpoints.

These tests use an in-memory SQLite database via StaticPool so they run
without a live PostgreSQL instance.  Array columns are stubbed with JSON
so openpyxl / asyncpg are not required at test time.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.base import Base

# ---------------------------------------------------------------------------
# Test database — SQLite in-memory with asyncio support
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh SQLite AsyncSession per test."""
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
    )

    # SQLite doesn't have ARRAY; swap it for JSON on the metadata level
    from sqlalchemy.dialects import sqlite as sqlite_dialect
    from app.models.consignment import Consignment

    # Patch the part_numbers column type for SQLite
    col = Consignment.__table__.c.part_numbers
    col.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with the DB session overridden."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_vendor(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/schedule/vendors",
        json={
            "vendor_code": "V001",
            "name": "Test Vendor Ltd",
            "contact_name": "Ramesh Kumar",
            "contact_phone": "9876543210",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tests — Vendors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_vendor(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    assert vendor["vendor_code"] == "V001"
    assert vendor["name"] == "Test Vendor Ltd"
    assert "id" in vendor


@pytest.mark.asyncio
async def test_create_vendor_duplicate_code(client: AsyncClient) -> None:
    await _create_vendor(client)
    resp = await client.post(
        "/api/v1/schedule/vendors",
        json={"vendor_code": "V001", "name": "Duplicate Vendor"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Tests — Consignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_consignment(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    vendor_id = vendor["id"]

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    slot_start = now + timedelta(hours=1)
    slot_end = now + timedelta(hours=2)

    resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor_id,
            "bay_code": "BAY-01",
            "part_numbers": ["P100", "P200"],
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["vendor_id"] == vendor_id
    assert data["bay_code"] == "BAY-01"
    assert data["status"] == "SCHEDULED"
    assert data["part_numbers"] == ["P100", "P200"]


@pytest.mark.asyncio
async def test_create_consignment_unknown_vendor(client: AsyncClient) -> None:
    now = datetime.now(tz=timezone.utc)
    resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": str(uuid.uuid4()),
            "slot_start": now.isoformat(),
            "slot_end": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_consignment(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)

    create_resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": now.isoformat(),
            "slot_end": (now + timedelta(hours=1)).isoformat(),
        },
    )
    consignment_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/schedule/consignments/{consignment_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == consignment_id


@pytest.mark.asyncio
async def test_update_consignment_status(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)

    create_resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": now.isoformat(),
            "slot_end": (now + timedelta(hours=1)).isoformat(),
            "truck_plate": "MH12AB1234",
        },
    )
    consignment_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/schedule/consignments/{consignment_id}",
        json={"status": "TRUCK_REGISTERED", "driver_phone": "9876543210"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "TRUCK_REGISTERED"
    assert data["driver_phone"] == "9876543210"


@pytest.mark.asyncio
async def test_list_consignments_filter_by_date(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    today = date.today()
    slot_start = datetime(today.year, today.month, today.day, 9, 0, tzinfo=timezone.utc)
    slot_end = slot_start + timedelta(hours=1)

    await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
        },
    )

    resp = await client.get(f"/api/v1/schedule/consignments?date={today.isoformat()}")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_assign_bay(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)

    create_resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": now.isoformat(),
            "slot_end": (now + timedelta(hours=1)).isoformat(),
        },
    )
    consignment_id = create_resp.json()["id"]
    bay_id = str(uuid.uuid4())

    resp = await client.post(
        f"/api/v1/schedule/consignments/{consignment_id}/assign-bay",
        json={"bay_id": bay_id, "bay_code": "BAY-03"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bay_code"] == "BAY-03"
    assert data["bay_id"] == bay_id


# ---------------------------------------------------------------------------
# Tests — Gate check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_check_found(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    slot_start = now + timedelta(minutes=10)  # within early window (30 min)

    await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "truck_plate": "MH12XY9999",
            "bay_code": "BAY-05",
        },
    )

    resp = await client.get("/api/v1/schedule/consignments/check/MH12XY9999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bay_code"] == "BAY-05"
    assert data["status"] == "SCHEDULED"


@pytest.mark.asyncio
async def test_gate_check_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/schedule/consignments/check/ZZNOTEXIST")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — Gantt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gantt_empty_date(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/schedule/gantt?date=2099-01-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2099-01-01"
    assert data["blocks"] == []


@pytest.mark.asyncio
async def test_gantt_with_consignments(client: AsyncClient) -> None:
    vendor = await _create_vendor(client)
    today = date.today()
    slot_start = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
    slot_end = slot_start + timedelta(hours=1)

    create_resp = await client.post(
        "/api/v1/schedule/consignments",
        json={
            "vendor_id": vendor["id"],
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
            "bay_code": "BAY-02",
            "truck_plate": "KA05HJ4321",
        },
    )
    assert create_resp.status_code == 201

    resp = await client.get(f"/api/v1/schedule/gantt?date={today.isoformat()}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["blocks"]) >= 1
    block = data["blocks"][0]
    assert block["bay_code"] == "BAY-02"
    assert block["vendor_name"] == "Test Vendor Ltd"
    assert block["truck_plate"] == "KA05HJ4321"


# ---------------------------------------------------------------------------
# Tests — Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/schedule/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
