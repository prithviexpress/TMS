"""Tests for the bay-service.

Test strategy:
- Use an in-memory SQLite database (via aiosqlite) so tests run without
  Postgres, Redis, or NATS.
- Mock Redis (async mock) and NATS client so no external services are needed.
- Use httpx.AsyncClient with ASGITransport to exercise the real FastAPI app.

Covered cases:
1. GET /api/v1/bays — list all bays (cold cache falls back to DB).
2. POST /api/v1/bays/sensor/ingest — sensor webhook updates bay status.
3. GET /api/v1/bays/events/stream — SSE endpoint returns 200 with text/event-stream.
4. GET /api/v1/bays/health — liveness probe.
5. PATCH /api/v1/bays/{bay_id}/assign — assign truck to bay.
6. PATCH /api/v1/bays/{bay_id}/release — release bay back to VACANT.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.cache import get_redis, set_bay_status
from app.models.bay import Bay
from app.models.bay_occupancy import BayOccupancy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create an in-memory SQLite async engine for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh async DB session bound to the in-memory engine."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def sample_bay(db_session: AsyncSession) -> Bay:
    """Insert a sample Bay + BayOccupancy (VACANT) into the test DB."""
    bay = Bay(
        id=uuid.uuid4(),
        bay_code="AR-N1",
        zone="AR",
        sensor_device_eui="AABBCCDDEEFF0011",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(bay)
    await db_session.flush()

    occ = BayOccupancy(
        id=uuid.uuid4(),
        bay_id=bay.id,
        status="VACANT",
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(occ)
    await db_session.commit()
    return bay


@pytest.fixture
def mock_redis():
    """Return an AsyncMock that behaves like a redis.asyncio.Redis client."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    # scan_iter should yield nothing by default
    async def _empty_scan(*args, **kwargs):
        return
        yield  # make it an async generator

    r.scan_iter = _empty_scan
    return r


@pytest.fixture
def mock_nats():
    """Return a MagicMock that behaves like a NATS client with JetStream."""
    nc = MagicMock()
    js = AsyncMock()
    js.publish = AsyncMock(return_value=None)
    nc.jetstream = MagicMock(return_value=js)
    return nc


@pytest_asyncio.fixture
async def test_app(db_session: AsyncSession, mock_redis, mock_nats) -> FastAPI:
    """Build the FastAPI app with all external dependencies overridden."""
    # Import here to avoid module-level side effects in tests
    from app.main import create_app

    application = create_app()

    # Override DB dependency
    async def _override_db():
        yield db_session

    # Override Redis dependency
    async def _override_redis():
        yield mock_redis

    application.dependency_overrides[get_db] = _override_db
    application.dependency_overrides[get_redis] = _override_redis

    # Attach mock NATS client to app state (lifespan doesn't run in test)
    application.state.nats_client = mock_nats

    return application


@pytest_asyncio.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx AsyncClient wired to the test FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper: build a valid JWT for protected routes
# ---------------------------------------------------------------------------

def _make_jwt() -> str:
    """Create a signed JWT using the test JWT_SECRET."""
    from jose import jwt as jose_jwt
    import os
    secret = os.environ.get("JWT_SECRET", "changeme")
    payload = {
        "sub": "test-user",
        "exp": 9999999999,
        "iat": 1000000000,
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client: AsyncClient):
        resp = await client.get("/api/v1/bays/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestListBays:
    async def test_list_bays_empty_cache_falls_back_to_db(
        self,
        client: AsyncClient,
        sample_bay: Bay,
    ):
        """With a cold Redis cache, GET /bays should still return bay data from DB."""
        resp = await client.get("/api/v1/bays")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # At least the sample bay should appear
        codes = [item["bay_code"] for item in data]
        assert "AR-N1" in codes

    async def test_list_bays_from_cache(
        self,
        client: AsyncClient,
        sample_bay: Bay,
        mock_redis,
    ):
        """When Redis has data, list_bays serves it without hitting the DB."""
        cached_entry = {
            "bay_code": "AR-N1",
            "zone": "AR",
            "status": "OCCUPIED",
            "vendor_name": "Bosch",
            "truck_plate": "MH02AB1234",
            "occupied_at": "2026-01-01T10:00:00+00:00",
            "time_left_minutes": 30,
        }

        # Make scan_iter yield one key, get return the cached entry
        async def _scan(*args, **kwargs):
            yield "bay:AR-N1:status"

        mock_redis.scan_iter = _scan
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_entry))

        resp = await client.get("/api/v1/bays")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item["bay_code"] == "AR-N1" and item["status"] == "OCCUPIED" for item in data)

    async def test_list_bays_filter_by_zone(
        self,
        client: AsyncClient,
        sample_bay: Bay,
    ):
        """Zone filter should only return bays in that zone."""
        resp = await client.get("/api/v1/bays?zone=AR")
        assert resp.status_code == 200
        data = resp.json()
        for item in data:
            assert item["bay_code"].startswith("AR")


class TestSensorIngest:
    """Tests for POST /api/v1/bays/sensor/ingest."""

    _VALID_PAYLOAD = {
        "deviceInfo": {
            "devEui": "AABBCCDDEEFF0011",
            "deviceName": "bay-AR-N1",
        },
        "object": {
            "distance": 200,      # 200 cm → 2000 mm → OCCUPIED
            "temperature": 28.5,
        },
        "data": None,
    }

    async def test_missing_api_key_returns_401(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/bays/sensor/ingest",
            json=self._VALID_PAYLOAD,
        )
        assert resp.status_code == 401

    async def test_wrong_api_key_returns_401(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/bays/sensor/ingest",
            json=self._VALID_PAYLOAD,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    @patch("app.routers.sensor.process_sensor_update", new_callable=AsyncMock)
    async def test_valid_sensor_payload_updates_status(
        self,
        mock_process,
        client: AsyncClient,
        sample_bay: Bay,
        mock_redis,
    ):
        """A valid sensor webhook with the correct API key should return 204."""
        import os
        api_key = os.environ.get("LORAWAN_INGEST_API_KEY", "changeme")

        # Mock get_bay_status to return None (no cached entry to broadcast)
        mock_redis.get = AsyncMock(return_value=None)

        resp = await client.post(
            "/api/v1/bays/sensor/ingest",
            json=self._VALID_PAYLOAD,
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 204
        mock_process.assert_awaited_once()

    @patch("app.routers.sensor.process_sensor_update", new_callable=AsyncMock)
    async def test_unknown_device_eui_stores_orphan(
        self,
        mock_process,
        client: AsyncClient,
        sample_bay: Bay,
    ):
        """A webhook from an unknown DevEUI should be stored but not cause a state transition."""
        import os
        api_key = os.environ.get("LORAWAN_INGEST_API_KEY", "changeme")

        payload = {
            "deviceInfo": {"devEui": "DEADBEEF00000000"},
            "object": {"distance": 100, "temperature": 25.0},
        }
        resp = await client.post(
            "/api/v1/bays/sensor/ingest",
            json=payload,
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 204
        # process_sensor_update should NOT have been called for an unknown device
        mock_process.assert_not_awaited()

    async def test_sensor_payload_vacant_distance(self, client: AsyncClient, sample_bay: Bay):
        """Distance above threshold (>= 500 mm) should result in VACANT occupancy verdict."""
        from app.services.sensor_decoder import decode_chirpstack_payload

        payload = {
            "deviceInfo": {"devEui": "AABBCCDDEEFF0011"},
            "object": {"distance": 600},  # 600 cm = 6000 mm → VACANT
        }
        _eui, occupied, distance_mm, _temp = decode_chirpstack_payload(payload)
        assert occupied is False
        assert distance_mm == 6000

    async def test_sensor_payload_occupied_distance(self, client: AsyncClient):
        """Distance below threshold (< 500 mm) should result in OCCUPIED occupancy verdict."""
        from app.services.sensor_decoder import decode_chirpstack_payload

        payload = {
            "deviceInfo": {"devEui": "AABBCCDDEEFF0011"},
            "object": {"distance": 30},  # 30 cm = 300 mm → OCCUPIED
        }
        _eui, occupied, distance_mm, _temp = decode_chirpstack_payload(payload)
        assert occupied is True
        assert distance_mm == 300


class TestSSEStream:
    async def test_sse_endpoint_returns_200_with_event_stream(self, client: AsyncClient):
        """SSE endpoint should return 200 with text/event-stream content type."""
        async with client.stream("GET", "/api/v1/bays/events/stream") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            # Read the initial comment line
            async for line in resp.aiter_lines():
                # First non-empty line should be the "connected" comment
                if line.strip():
                    assert ": connected" in line or "data:" in line or ": heartbeat" in line
                    break


class TestBayAssignRelease:
    """Tests for PATCH assign/release endpoints."""

    async def test_assign_returns_404_for_unknown_bay(self, client: AsyncClient):
        token = _make_jwt()
        resp = await client.patch(
            f"/api/v1/bays/{uuid.uuid4()}/assign",
            json={
                "movement_id": str(uuid.uuid4()),
                "vendor_name": "Bosch",
                "truck_plate": "MH02AB1234",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @patch("app.routers.bays.assign_bay", new_callable=AsyncMock)
    async def test_assign_bay_returns_bay_response(
        self,
        mock_assign,
        client: AsyncClient,
        sample_bay: Bay,
        db_session: AsyncSession,
        mock_redis,
    ):
        """PATCH /assign should call assign_bay and return a BayResponse."""
        # assign_bay returns a BayOccupancy; we mock it to avoid NATS/display calls
        occ = BayOccupancy(
            id=uuid.uuid4(),
            bay_id=sample_bay.id,
            status="RESERVED",
            updated_at=datetime.now(timezone.utc),
        )
        mock_assign.return_value = occ
        mock_redis.get = AsyncMock(return_value=None)

        token = _make_jwt()
        movement_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/bays/{sample_bay.id}/assign",
            json={"movement_id": movement_id, "vendor_name": "Bosch", "truck_plate": "MH02AB1234"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bay_code"] == "AR-N1"

    @patch("app.routers.bays.release_bay", new_callable=AsyncMock)
    async def test_release_bay_returns_vacant(
        self,
        mock_release,
        client: AsyncClient,
        sample_bay: Bay,
        mock_redis,
    ):
        """PATCH /release should call release_bay and return a BayResponse."""
        occ = BayOccupancy(
            id=uuid.uuid4(),
            bay_id=sample_bay.id,
            status="VACANT",
            updated_at=datetime.now(timezone.utc),
        )
        mock_release.return_value = occ
        mock_redis.get = AsyncMock(return_value=None)

        token = _make_jwt()
        resp = await client.patch(
            f"/api/v1/bays/{sample_bay.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bay_code"] == "AR-N1"


class TestSensorDecoder:
    """Unit tests for sensor_decoder.decode_chirpstack_payload."""

    def test_decode_with_object_distance_cm(self):
        from app.services.sensor_decoder import decode_chirpstack_payload

        raw = {
            "deviceInfo": {"devEui": "AA:BB:CC:DD:EE:FF:00:11"},
            "object": {"distance": 45, "temperature": 30.0},
        }
        eui, occupied, dist, temp = decode_chirpstack_payload(raw)
        assert eui == "AA:BB:CC:DD:EE:FF:00:11"
        assert dist == 450  # 45 cm → 450 mm
        assert occupied is True
        assert temp == 30.0

    def test_decode_with_object_boolean_occupied(self):
        from app.services.sensor_decoder import decode_chirpstack_payload

        raw = {
            "deviceInfo": {"devEui": "DEADBEEF"},
            "object": {"occupied": True, "temperature": 25.0},
        }
        _eui, occupied, _dist, _temp = decode_chirpstack_payload(raw)
        assert occupied is True

    def test_decode_missing_eui_raises(self):
        from app.services.sensor_decoder import decode_chirpstack_payload
        import pytest

        with pytest.raises(ValueError, match="devEui"):
            decode_chirpstack_payload({"deviceInfo": {}})

    def test_decode_no_distance_defaults_to_not_occupied(self):
        from app.services.sensor_decoder import decode_chirpstack_payload

        raw = {
            "deviceInfo": {"devEui": "DEADBEEF"},
            "object": {"temperature": 22.0},
        }
        _eui, occupied, dist, _temp = decode_chirpstack_payload(raw)
        assert occupied is False
        assert dist is None

    def test_decode_raw_base64_data(self):
        """EM400-MUD raw payload: 2-byte LE uint16 distance in cm at offset 0."""
        import struct
        import base64
        from app.services.sensor_decoder import decode_chirpstack_payload

        # 30 cm = 0x001E in little-endian
        raw_bytes = struct.pack("<H", 30) + bytes([0x00, 0x01])
        b64 = base64.b64encode(raw_bytes).decode()

        raw = {
            "deviceInfo": {"devEui": "TESTDEVICE"},
            "data": b64,
        }
        _eui, occupied, dist_mm, _temp = decode_chirpstack_payload(raw)
        # 30 cm → 300 mm → OCCUPIED
        assert dist_mm == 300
        assert occupied is True
