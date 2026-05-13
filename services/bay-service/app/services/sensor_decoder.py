"""Decode raw Chirpstack webhook payloads from Milesight EM400-MUD sensors.

The EM400-MUD is an ultrasonic distance sensor used to detect bay occupancy.
Chirpstack delivers either:
  1. A decoded ``object`` (when a LoRa codec is configured), or
  2. A raw base64-encoded ``data`` field.

Occupancy threshold: distance_mm < 500 mm → OCCUPIED.

This module is pure Python with no I/O so it is trivially testable.
"""

from __future__ import annotations

import base64
import logging
import struct

from app.config import settings

logger = logging.getLogger(__name__)

# Default occupancy threshold — also configurable via Settings
_OCCUPANCY_THRESHOLD_MM = settings.OCCUPANCY_DISTANCE_THRESHOLD_MM


def _distance_from_raw_bytes(data_b64: str) -> int | None:
    """Attempt to decode distance from a raw EM400-MUD payload.

    The EM400-MUD FPort 5 payload encodes distance as a little-endian
    uint16 at byte offset 0 (in centimetres for older firmware, mm for newer).
    We return millimetres in both cases by heuristically checking the magnitude.

    Returns ``None`` if decoding fails.
    """
    try:
        raw = base64.b64decode(data_b64)
    except Exception:
        logger.debug("Failed to base64-decode sensor data field")
        return None

    if len(raw) < 2:
        logger.debug("Raw payload too short to extract distance: %d bytes", len(raw))
        return None

    try:
        # Bytes 0-1: distance as little-endian uint16
        (value,) = struct.unpack_from("<H", raw, 0)
    except struct.error:
        return None

    # Heuristic: values > 10 000 are almost certainly mm already;
    # values ≤ 10 000 and ≥ 1 are assumed to be cm → convert to mm.
    if value == 0:
        return None
    if value <= 10_000:
        return value * 10  # cm → mm
    return value  # already mm


def decode_chirpstack_payload(raw: dict) -> tuple[str, bool, int | None, float | None]:
    """Decode a Chirpstack uplink dict into structured sensor values.

    Args:
        raw: The full parsed Chirpstack JSON body as a Python dict.

    Returns:
        A 4-tuple ``(device_eui, occupied, distance_mm, temperature_c)``.
        ``distance_mm`` and ``temperature_c`` may be ``None`` when unavailable.

    Raises:
        ValueError: If ``deviceInfo.devEui`` is missing from *raw*.
    """
    device_info = raw.get("deviceInfo", {})
    device_eui: str = device_info.get("devEui", "")
    if not device_eui:
        raise ValueError("Missing deviceInfo.devEui in Chirpstack payload")

    distance_mm: int | None = None
    temperature_c: float | None = None
    occupied: bool | None = None

    # ── Path 1: decoded ``object`` from Chirpstack codec ─────────────────────
    obj = raw.get("object")
    if obj and isinstance(obj, dict):
        # Some Milesight firmware variants report distance in cm
        if "distance" in obj:
            raw_distance = obj["distance"]
            if isinstance(raw_distance, (int, float)) and raw_distance > 0:
                # Heuristic: if the value is <= 10000 treat as cm
                if raw_distance <= 10_000:
                    distance_mm = int(raw_distance * 10)
                else:
                    distance_mm = int(raw_distance)

        # Alternative key name used in some codec versions
        if distance_mm is None and "distance_cm" in obj:
            raw_distance = obj["distance_cm"]
            if isinstance(raw_distance, (int, float)) and raw_distance > 0:
                distance_mm = int(raw_distance * 10)

        # Some codecs emit an explicit boolean
        if "occupied" in obj and isinstance(obj["occupied"], bool):
            occupied = obj["occupied"]

        if "temperature" in obj and isinstance(obj["temperature"], (int, float)):
            temperature_c = float(obj["temperature"])

    # ── Path 2: raw base64 ``data`` field ────────────────────────────────────
    if distance_mm is None:
        data_b64 = raw.get("data")
        if data_b64 and isinstance(data_b64, str):
            distance_mm = _distance_from_raw_bytes(data_b64)

    # ── Determine occupancy ──────────────────────────────────────────────────
    if occupied is None:
        if distance_mm is not None:
            occupied = distance_mm < _OCCUPANCY_THRESHOLD_MM
        else:
            # No distance data; default to not occupied (safe default)
            logger.warning(
                "DevEUI %s: no distance data in payload — defaulting to NOT occupied",
                device_eui,
            )
            occupied = False

    logger.debug(
        "Decoded sensor: eui=%s occupied=%s dist_mm=%s temp_c=%s",
        device_eui,
        occupied,
        distance_mm,
        temperature_c,
    )
    return device_eui, occupied, distance_mm, temperature_c
