"""Pydantic v2 schemas for Chirpstack LoRaWAN webhook payloads.

Chirpstack sends a JSON body that contains either:
  - A decoded ``object`` field (when a codec is configured), or
  - A raw base64-encoded ``data`` field (fallback).

The Milesight EM400-MUD codec decodes into an ``object`` that typically
contains ``distance`` (mm) and optionally ``temperature`` (°C).

References
----------
* Chirpstack v4 HTTP integration docs
* Milesight EM400-MUD payload format specification v1.3
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Chirpstack webhook sub-models
# ---------------------------------------------------------------------------


class DeviceInfo(BaseModel):
    """Device metadata block included in every Chirpstack uplink."""

    devEui: str
    deviceName: str | None = None
    applicationName: str | None = None
    tenantName: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class DecodedObject(BaseModel):
    """Optional decoded sensor values (present when a codec is configured).

    Field names follow Milesight EM400-MUD codec output conventions.
    All fields are optional because the codec may omit them on certain
    port/frame combinations.
    """

    distance: int | None = None          # cm or mm depending on firmware
    distance_cm: int | None = None       # alternative name used in some versions
    occupied: bool | None = None         # direct boolean if codec provides it
    temperature: float | None = None
    battery: int | None = None
    # Catch-all for other decoded fields we don't specifically handle
    model_config = {"extra": "allow"}


class ChirpstackPayload(BaseModel):
    """Top-level Chirpstack HTTP integration uplink message.

    Only the fields the bay-service cares about are modelled here.
    Unknown extra fields are silently ignored.
    """

    model_config = {"extra": "ignore"}

    deviceInfo: DeviceInfo
    data: str | None = None              # base64-encoded raw payload
    object: DecodedObject | None = None  # decoded values (codec output)

    # Chirpstack includes a timestamp in ISO 8601 format
    time: str | None = None

    # rxInfo / txInfo arrays — we don't use them but include for completeness
    rxInfo: list[Any] = Field(default_factory=list)
    txInfo: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_eui(self) -> "ChirpstackPayload":
        if not self.deviceInfo.devEui:
            raise ValueError("deviceInfo.devEui is required")
        return self


# ---------------------------------------------------------------------------
# Parsed result (output of sensor_decoder.decode_chirpstack_payload)
# ---------------------------------------------------------------------------


class SensorIngestResult(BaseModel):
    """Clean, normalised sensor reading after decoding the raw Chirpstack body."""

    device_eui: str
    occupied: bool
    distance_mm: int | None = None
    temperature_c: float | None = None
