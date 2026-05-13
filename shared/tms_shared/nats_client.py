"""Async NATS connection factory and JetStream stream initialisation."""

from __future__ import annotations

import logging

import nats
import nats.js.api
from nats.errors import BadSubscriptionError
from nats.js.api import RetentionPolicy, StorageType, StreamConfig

logger = logging.getLogger(__name__)

# 7 days in seconds
_MAX_AGE_SECONDS = 86400 * 7

_STREAM_DEFINITIONS: list[tuple[str, list[str]]] = [
    ("TMS_GATE", ["tms.gate.*", "alpr.>"]),
    ("TMS_BAY", ["tms.bay.*"]),
    ("TMS_SCHEDULE", ["tms.schedule.*"]),
    ("TMS_VENDOR", ["tms.vendor.*"]),
]


async def get_nats_client(url: str) -> nats.NATS:
    """Connect to NATS and return the client instance.

    Args:
        url: NATS server URL, e.g. ``"nats://localhost:4222"``.

    Returns:
        A connected :class:`nats.NATS` client.
    """
    nc = await nats.connect(url)
    logger.info("Connected to NATS at %s", url)
    return nc


async def init_jetstream_streams(js: nats.js.JetStreamContext) -> None:
    """Create the four TMS JetStream streams if they do not already exist.

    Existing streams (identified by :class:`BadSubscriptionError`) are left
    untouched so the function is safe to call on every startup.

    Args:
        js: An active JetStream context obtained from ``nc.jetstream()``.
    """
    for stream_name, subjects in _STREAM_DEFINITIONS:
        config = StreamConfig(
            name=stream_name,
            subjects=subjects,
            retention=RetentionPolicy.LIMITS,
            max_age=_MAX_AGE_SECONDS,
            storage=StorageType.FILE,
        )
        try:
            await js.add_stream(config=config)
            logger.info("Created JetStream stream '%s' with subjects %s", stream_name, subjects)
        except BadSubscriptionError:
            logger.info("JetStream stream '%s' already exists – skipping creation", stream_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create stream '%s': %s", stream_name, exc)
            raise
