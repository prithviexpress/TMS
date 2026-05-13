#!/bin/bash
# init-streams.sh — Create TMS JetStream streams after NATS is ready.
# Called once by the nats-init one-shot Docker service.

set -euo pipefail

NATS_OPTS="--server nats://nats:4222"

# ── Wait for NATS to be healthy ────────────────────────────────────────────────
echo "Waiting for NATS server at nats://nats:4222 ..."
until nats server check ${NATS_OPTS} 2>/dev/null; do
  echo "  NATS not ready yet, retrying in 2 s..."
  sleep 2
done
echo "NATS is ready."

# ── Helper: create-or-update a stream ─────────────────────────────────────────
# Usage: create_stream <name> <subjects> <max-age> [extra flags...]
create_stream() {
  local name="$1"
  local subjects="$2"
  local max_age="$3"
  shift 3

  echo "Creating stream ${name} (subjects: ${subjects}, max-age: ${max_age})..."
  nats stream add "${name}" ${NATS_OPTS} \
    --subjects "${subjects}" \
    --storage file \
    --retention limits \
    --max-age "${max_age}" \
    --replicas 1 \
    --discard old \
    --defaults \
    "$@" 2>/dev/null \
  || nats stream edit "${name}" ${NATS_OPTS} \
       --subjects "${subjects}" \
       --max-age "${max_age}" \
       "$@" 2>/dev/null \
  || true

  echo "  Stream ${name} OK."
}

# ── TMS_GATE — gate entry/exit events + ALPR camera frames ───────────────────
create_stream TMS_GATE "tms.gate.*,alpr.>" 168h

# ── TMS_BAY — bay occupancy, sensor readings ──────────────────────────────────
create_stream TMS_BAY "tms.bay.*" 168h

# ── TMS_SCHEDULE — slot updates, consignment state changes ────────────────────
create_stream TMS_SCHEDULE "tms.schedule.*" 168h

# ── TMS_VENDOR — vendor self-registration events ──────────────────────────────
create_stream TMS_VENDOR "tms.vendor.*" 168h

# ── TMS_DLQ — dead-letter queue for failed / unprocessable events ─────────────
create_stream TMS_DLQ "tms.dlq.*" 720h

echo ""
echo "All NATS JetStream streams initialized successfully."
