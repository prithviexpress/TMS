"""Tests for gate_logic: evaluate_truck_arrival decision logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest
import httpx

from app.services.gate_logic import evaluate_truck_arrival

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
_SCHEDULE_URL = "http://schedule-service:8003"


def _make_mock_response(status_code: int, data: dict | None = None) -> httpx.Response:
    """Create a mock httpx.Response."""
    content = json.dumps(data or {}).encode()
    return httpx.Response(status_code=status_code, content=content)


def _make_http_client(response: httpx.Response) -> httpx.AsyncClient:
    """Return an AsyncClient whose .get() returns a fixed response."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# evaluate_truck_arrival tests
# ---------------------------------------------------------------------------


class TestEvaluateTruckArrivalAllow:
    """Truck arrives within the allowed Nagare window → action='allow'."""

    @pytest.mark.asyncio
    async def test_allow_on_time(self):
        """Truck arrives exactly at slot start → allow."""
        slot_start = _NOW  # minutes_to_slot == 0
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000001",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B01",
            "bay_id": "00000000-0000-0000-0000-000000000011",
            "vendor_id": "00000000-0000-0000-0000-000000000021",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02AB1234", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "allow"
        assert result["rejection_reason"] is None
        assert result["minutes_to_slot"] == 0
        assert result["bay_code"] == "B01"

    @pytest.mark.asyncio
    async def test_allow_30_minutes_early(self):
        """Truck arrives 30 minutes before slot → allow (within window)."""
        slot_start = _NOW + timedelta(minutes=30)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000002",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B02",
            "bay_id": "00000000-0000-0000-0000-000000000012",
            "vendor_id": "00000000-0000-0000-0000-000000000022",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02AB5678", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "allow"
        assert result["minutes_to_slot"] == 30
        assert result["rejection_reason"] is None

    @pytest.mark.asyncio
    async def test_allow_exactly_60_minutes_early(self):
        """Truck arrives exactly 60 minutes early → allow (boundary inclusive)."""
        slot_start = _NOW + timedelta(minutes=60)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000003",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B03",
            "bay_id": "00000000-0000-0000-0000-000000000013",
            "vendor_id": "00000000-0000-0000-0000-000000000023",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02CD0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "allow"
        assert result["minutes_to_slot"] == 60

    @pytest.mark.asyncio
    async def test_allow_30_minutes_late(self):
        """Truck arrives 30 minutes after slot start → allow (within late window)."""
        slot_start = _NOW - timedelta(minutes=30)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000004",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B04",
            "bay_id": "00000000-0000-0000-0000-000000000014",
            "vendor_id": "00000000-0000-0000-0000-000000000024",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02CD0002", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "allow"
        assert result["minutes_to_slot"] == -30


class TestEvaluateTruckArrivalHold:
    """Truck arrives more than 60 min before slot → action='hold'."""

    @pytest.mark.asyncio
    async def test_hold_61_minutes_early(self):
        """61 minutes early → hold."""
        slot_start = _NOW + timedelta(minutes=61)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000005",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B05",
            "bay_id": "00000000-0000-0000-0000-000000000015",
            "vendor_id": "00000000-0000-0000-0000-000000000025",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02EF0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "hold"
        assert result["minutes_to_slot"] == 61
        assert "early" in result["rejection_reason"].lower()

    @pytest.mark.asyncio
    async def test_hold_2_hours_early(self):
        """2 hours early → hold."""
        slot_start = _NOW + timedelta(hours=2)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000006",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B06",
            "bay_id": "00000000-0000-0000-0000-000000000016",
            "vendor_id": "00000000-0000-0000-0000-000000000026",
            "status": "active",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02EF0002", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "hold"
        assert result["minutes_to_slot"] == 120


class TestEvaluateTruckArrivalReject:
    """Various rejection scenarios."""

    @pytest.mark.asyncio
    async def test_reject_not_in_schedule_404(self):
        """Schedule-service returns 404 → reject."""
        response = _make_mock_response(404)
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("XX00ZZ9999", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert result["rejection_reason"] == "Not in schedule"
        assert result["consignment_id"] is None
        assert result["minutes_to_slot"] is None

    @pytest.mark.asyncio
    async def test_reject_too_late_31_minutes(self):
        """Truck arrives 31 minutes after slot start → reject (too late)."""
        slot_start = _NOW - timedelta(minutes=31)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000007",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B07",
            "bay_id": "00000000-0000-0000-0000-000000000017",
            "vendor_id": "00000000-0000-0000-0000-000000000027",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02GH0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert result["minutes_to_slot"] == -31
        assert "late" in result["rejection_reason"].lower()

    @pytest.mark.asyncio
    async def test_reject_too_late_2_hours(self):
        """Truck arrives 2 hours after slot start → reject."""
        slot_start = _NOW - timedelta(hours=2)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000008",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": None,
            "bay_id": None,
            "vendor_id": "00000000-0000-0000-0000-000000000028",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02GH0002", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert result["minutes_to_slot"] == -120

    @pytest.mark.asyncio
    async def test_reject_no_active_consignment(self):
        """Schedule-service returns 200 but status is not active → reject."""
        slot_start = _NOW + timedelta(minutes=10)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000009",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B09",
            "bay_id": "00000000-0000-0000-0000-000000000019",
            "vendor_id": "00000000-0000-0000-0000-000000000029",
            "status": "cancelled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02IJ0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert result["rejection_reason"] == "No active consignment"

    @pytest.mark.asyncio
    async def test_reject_schedule_service_error(self):
        """Schedule-service returns 500 → reject."""
        response = _make_mock_response(500, {"detail": "Internal Server Error"})
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02KL0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert "500" in result["rejection_reason"]

    @pytest.mark.asyncio
    async def test_reject_schedule_service_unreachable(self):
        """Network error reaching schedule-service → reject."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        result = await evaluate_truck_arrival("MH02MN0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert "unreachable" in result["rejection_reason"].lower()

    @pytest.mark.asyncio
    async def test_reject_no_slot_time(self):
        """Schedule-service returns record without slot_start → reject."""
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000010",
            "slot_start": None,
            "slot_end": None,
            "bay_code": None,
            "bay_id": None,
            "vendor_id": "00000000-0000-0000-0000-000000000030",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02OP0001", _NOW, _SCHEDULE_URL, client)

        assert result["action"] == "reject"
        assert "slot" in result["rejection_reason"].lower()


class TestMinutesToSlotCalculation:
    """Verify correct minutes_to_slot arithmetic under various conditions."""

    @pytest.mark.asyncio
    async def test_minutes_to_slot_positive_means_early(self):
        """Positive minutes_to_slot means truck is early."""
        slot_start = _NOW + timedelta(minutes=45)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000011",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B11",
            "bay_id": "00000000-0000-0000-0000-000000000031",
            "vendor_id": "00000000-0000-0000-0000-000000000041",
            "status": "confirmed",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02QR0001", _NOW, _SCHEDULE_URL, client)

        assert result["minutes_to_slot"] == 45
        assert result["action"] == "allow"

    @pytest.mark.asyncio
    async def test_minutes_to_slot_negative_means_late(self):
        """Negative minutes_to_slot means truck is late."""
        slot_start = _NOW - timedelta(minutes=15)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000012",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B12",
            "bay_id": "00000000-0000-0000-0000-000000000032",
            "vendor_id": "00000000-0000-0000-0000-000000000042",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02QR0002", _NOW, _SCHEDULE_URL, client)

        assert result["minutes_to_slot"] == -15
        assert result["action"] == "allow"

    @pytest.mark.asyncio
    async def test_minutes_to_slot_truncated_to_int(self):
        """Fractional seconds in slot difference are truncated (not rounded)."""
        # 30 minutes and 45 seconds early → minutes_to_slot should be 30
        slot_start = _NOW + timedelta(minutes=30, seconds=45)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000013",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B13",
            "bay_id": "00000000-0000-0000-0000-000000000033",
            "vendor_id": "00000000-0000-0000-0000-000000000043",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02ST0001", _NOW, _SCHEDULE_URL, client)

        assert result["minutes_to_slot"] == 30  # int(), not round()

    @pytest.mark.asyncio
    async def test_slot_start_returned_in_result(self):
        """nagare_slot_start in result matches what schedule-service returned."""
        slot_start = _NOW + timedelta(minutes=20)
        slot_end = slot_start + timedelta(hours=1)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000014",
            "slot_start": slot_start.isoformat(),
            "slot_end": slot_end.isoformat(),
            "bay_code": "B14",
            "bay_id": "00000000-0000-0000-0000-000000000034",
            "vendor_id": "00000000-0000-0000-0000-000000000044",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02UV0001", _NOW, _SCHEDULE_URL, client)

        assert result["nagare_slot_start"] == slot_start
        assert result["action"] == "allow"

    @pytest.mark.asyncio
    async def test_naive_arrival_time_treated_as_utc(self):
        """Naive (tz-unaware) arrival_time is normalised to UTC without error."""
        naive_now = _NOW.replace(tzinfo=None)
        slot_start = _NOW + timedelta(minutes=10)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000015",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B15",
            "bay_id": "00000000-0000-0000-0000-000000000035",
            "vendor_id": "00000000-0000-0000-0000-000000000045",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        # Should not raise
        result = await evaluate_truck_arrival("MH02WX0001", naive_now, _SCHEDULE_URL, client)

        assert result["action"] == "allow"
        assert result["minutes_to_slot"] == 10

    @pytest.mark.asyncio
    async def test_boundary_exactly_minus_30_minutes(self):
        """Exactly -30 minutes (boundary): still allow."""
        slot_start = _NOW - timedelta(minutes=30)
        response = _make_mock_response(200, {
            "consignment_id": "00000000-0000-0000-0000-000000000016",
            "slot_start": slot_start.isoformat(),
            "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            "bay_code": "B16",
            "bay_id": "00000000-0000-0000-0000-000000000036",
            "vendor_id": "00000000-0000-0000-0000-000000000046",
            "status": "scheduled",
        })
        client = _make_http_client(response)

        result = await evaluate_truck_arrival("MH02YZ0001", _NOW, _SCHEDULE_URL, client)

        # -30 is NOT less than -30, so it should allow
        assert result["action"] == "allow"
        assert result["minutes_to_slot"] == -30
