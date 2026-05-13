# TMS — Updated Architecture Plan (v2)

## Context & What Changed

This revision incorporates 8 user-specified changes plus the detailed process flow (image 1) and enterprise feature list (image 2):

1. **Two ALPR + two LED**: One ALPR+LED at Gate, one ALPR+LED at Parking Exit
2. **All trucks park first**: No truck goes direct to bay — mandatory parking stop; bay call triggered by schedule window
3. **Material system entry at parking counter**: GR (Goods Receipt) entry done at parking, keyed by gate entry time
4. **Multi-bay per truck**: One truck can serve multiple bays based on attached consignments
5. **All config via Mendix**: Every variable (timeouts, thresholds, device IPs) configurable through Mendix
6. **Device Management service**: Add/remove/configure/monitor all IoT devices
7. **MQTT instead of Chirpstack webhook**: LoRaWAN sensor data arrives via MQTT (Mosquitto) not HTTP webhook
8. **Enterprise-grade API security**: OAuth2 scopes, rate limiting, mTLS service mesh, audit log, OpenTelemetry

---

## Revised Truck Lifecycle (Process Flow)

```
Truck Arrives at MSIL Gate
  │
  ├─ ALPR scans plate (alpr.gate.events)
  │   └─ Plate not found? → Manual entry by Guard → Trial/Entry not allowed
  │
  ├─ Retrieve Vendor + Supply time
  │   ├─ > 60 mins to slot → proceed to parking (early arrival)
  │   └─ < 60 mins to slot → proceed to parking (within window)
  │        └─ Delayed (< 0 Nagare time)? → Revise Worksheet:
  │             check vacant/urgent/emergency bays
  │
  [GATE LED: "PROCEED TO PARKING P-{number}", gate entry timestamp logged]
  │
  ▼
PARKING LOT  (all trucks wait here)
  │
  ├─ Material System Entry at parking counter
  │   └─ Entry identified by Gate Entry Time
  │        └─ Clerk/operator scans/enters: vendor, part numbers, qty expected
  │
  ├─ System monitors Bay/Time continuously
  │   ├─ < 15 mins to slot AND Bay VACANT → Call truck to bay
  │   │    └─ LED at parking: "PROCEED TO BAY AR-N1 NOW"
  │   │
  │   ├─ < 5 mins & Bay OCCUPIED → Check adjacent ±2 slots
  │   │    ├─ Unassigned slot found → redirect to alternate bay
  │   │    ├─ No alternate → redirect to emergency bay
  │   │    └─ If URGENT → proceed anyway (force-assign)
  │   │
  │   └─ > 15 mins wait at rest area → SLA alert → escalation
  │
  ▼
BAY  (truck may go to 1..N bays based on consignment)
  │
  ├─ LoRaWAN sensor (via MQTT) confirms truck present → K70 light GREEN
  ├─ Received Qty counter at bay: 0 → actual received count
  ├─ Bay Andon scheme (see below)
  ├─ Unloading complete → sensor vacated → K70 OFF
  │
  ├─ More consignments? → next bay assignment
  │
  ▼
PARKING EXIT
  ├─ All consignments done → truck proceeds to exit
  ├─ ALPR at parking exit scans plate (alpr.parking_exit.events)
  └─ LED at parking exit: "THANK YOU — SAFE JOURNEY"
```

### Bay Andon Color Scheme (K70 + Dashboard)

| Planned | Occupied | Warning | K70 Color | Mode |
|---|---|---|---|---|
| Yes | No | No | GREEN | Solid |
| Yes | Yes | No | AMBER | Blinking |
| No | Yes | Yes | RED | Solid |
| No | No | No | OFF | — |

---

## Services (9 total — 7 existing + 2 new)

### Existing services updated:

### 1. `gate-service` (port 8001) — UPDATED

**Changes:**
- Now handles BOTH `alpr.gate.events` AND `alpr.parking_exit.events`
- LED display IDs: `GATE_ENTRY` and `PARKING_EXIT` (both configurable)
- All timing thresholds (60 min, 15 min, 5 min, 30 min late) fetched from config-service
- Guard manual-entry fallback endpoint
- Idempotent event processing (deduplicate by `camera_id + plate + ts` within 30s window)
- Redis fallback: if schedule-service is unreachable, use last-known consignment state from cache

**Key endpoint additions:**
- `POST /api/v1/gate/manual-entry` — Guard creates manual truck entry
- `GET  /api/v1/gate/movements/{plate}/timeline` — Full journey timeline for a truck
- `GET  /api/v1/gate/sla-alerts` — Trucks exceeding parking dwell SLA

**NATS:**
- Consumes: `alpr.gate.events`, `alpr.parking_exit.events`
- Publishes: `tms.gate.truck_at_gate`, `tms.gate.truck_at_parking_exit`, `tms.gate.manual_entry`

---

### 2. `bay-service` (port 8002) — UPDATED

**Changes:**
- **MQTT subscriber** replaces HTTP webhook: connects to Mosquitto, subscribes to `lorawan/+/up` or `sensors/bays/#`
- **Sensor debouncing**: require 3 consecutive same-state readings before state flip (configurable)
- Multi-bay per truck: `bay_occupancy` now allows 1 movement_id → many bay records (truck may visit multiple bays)
- Andon color computed from `planned` + `occupied` + `warning` flags (see table above)
- Received qty tracking: `bay_receipts` table tracks part/qty received at each bay visit

**New endpoints:**
- `GET  /api/v1/bays/{bay_id}/receipts` — received qty log for a bay
- `POST /api/v1/bays/{bay_id}/receipts` — record received qty (called from bay counter UI)
- `GET  /api/v1/bays/digital-twin` — full bay grid with Andon status for Mendix digital twin

**New model:**
```sql
CREATE TABLE bay_receipts (
    id UUID PK,
    bay_id UUID FK bays(id),
    movement_id UUID,
    consignment_id UUID,
    part_number VARCHAR(50),
    expected_qty INT,
    received_qty INT DEFAULT 0,
    entry_time TIMESTAMPTZ,   -- matches parking entry time
    received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);
```

**MQTT integration:**
- Connect to `MQTT_BROKER_URL` (e.g. `mqtt://mosquitto:1883`) on startup
- Topic pattern: `lorawan/{device_eui}/up` → decode payload → occupancy state
- Debounce buffer: rolling window of last N readings per device

---

### 3. `schedule-service` (port 8003) — UPDATED

**Changes:**
- Consignments now support **1 truck → N bays**: `truck_plate` on `Truck` record; one truck has many `consignments`, each with a `bay_id` + `slot_start`
- Bay conflict resolution logic: `POST /api/v1/schedule/bays/resolve-conflicts` — when called, checks vacant bays, ±2 adjacent time slots, alternate bays, emergency bays
- Received qty updated via `PATCH /api/v1/schedule/consignments/{id}/receipt` — `{received_qty: int}`
- Centralized state machine: ALL consignment status changes go through schedule-service (other services call it rather than writing state directly)
- SLA monitoring: background task checks trucks in parking > SLA threshold, publishes `tms.schedule.sla_breach`

**New endpoints:**
- `POST /api/v1/schedule/bays/resolve-conflicts` — bay conflict resolution engine
- `GET  /api/v1/schedule/parking-queue` — trucks in parking waiting for bay call
- `PATCH /api/v1/schedule/consignments/{id}/receipt` — update received qty
- `GET  /api/v1/schedule/trucks/{plate}/consignments` — all consignments for a truck visit (multi-bay)
- `GET  /api/v1/schedule/trucks/{plate}/next-bay` — next bay to proceed to (for parking exit LED)

**Updated `consignments` table:**
```sql
ALTER TABLE consignments ADD COLUMN received_qty INT DEFAULT 0;
ALTER TABLE consignments ADD COLUMN expected_qty INT;
ALTER TABLE consignments ADD COLUMN material_entry_time TIMESTAMPTZ;  -- parking counter entry
ALTER TABLE consignments ADD COLUMN material_entry_by VARCHAR(100);
ALTER TABLE consignments ADD COLUMN is_urgent BOOLEAN DEFAULT FALSE;
ALTER TABLE consignments ADD COLUMN is_emergency BOOLEAN DEFAULT FALSE;
```

**New `truck_visits` table** (links one physical visit to many consignments):
```sql
CREATE TABLE truck_visits (
    id UUID PK,
    truck_plate VARCHAR(20) NOT NULL,
    vendor_id UUID FK,
    gate_entry_at TIMESTAMPTZ,   -- THE key identifier for material entry
    parking_entry_at TIMESTAMPTZ,
    parking_exit_at TIMESTAMPTZ,
    status VARCHAR(30),  -- IN_PARKING | AT_BAY | PARTIAL | COMPLETED | DEPARTED
    total_consignments INT,
    completed_consignments INT DEFAULT 0,
    created_at TIMESTAMPTZ
);
-- consignments.truck_visit_id FK → truck_visits.id
```

---

### 4. `vendor-service` (port 8004) — minor updates
- `GET /api/v1/vendors/{id}/truck-visits` — all visits with multi-bay summary
- No structural changes

---

### 5. `notification-service` (port 8005) — UPDATED
- New templates: `PARKING_CALL_TO_BAY`, `SLA_BREACH`, `MATERIAL_ENTRY_DONE`, `NEXT_BAY_READY`
- SLA breach alerts to logistics supervisor (configurable phone list)
- WhatsApp template approval flow for production

---

### 6. `display-service` (port 8006) — UPDATED

**Changes:**
- 4 hardware endpoints: GATE LED, PARKING EXIT LED (for vehicles), PARKING INTERNAL LED (for trucks waiting), PARKING COUNTER display
- K70 light control uses Andon color scheme (not just GREEN/OFF)
- Batch light updates: one API call to set N lights simultaneously
- Display command retry with exponential backoff

**New endpoints:**
- `POST /api/v1/display/lights/batch` — set many K70 lights atomically
- `GET  /api/v1/display/lights/andon-status` — all 160 lights current Andon state

**New NATS events consumed:**
- `tms.schedule.sla_breach` → flash red on parking display + SMS supervisor
- `tms.schedule.call_to_bay` → parking LED "PROCEED TO BAY AR-N1"

---

### 7. `auth-service` (port 8007) — UPDATED (Enterprise)

**Changes — enterprise security:**
- **OAuth2 scopes** alongside roles: `tms:read`, `tms:write`, `tms:admin`, `tms:device:write`, `tms:gate:override`
- Scope enforcement on every protected endpoint
- **API key management** for device integrations (ALPR cameras, MQTT, display hardware)
- `POST /api/v1/auth/api-keys` — generate scoped API keys for devices
- `DELETE /api/v1/auth/api-keys/{key_id}` — revoke
- **Audit log**: every write operation logged to `audit_events` table (who/what/when/IP)
- JWT short-lived (15 min access token, 7 day refresh with rotation)
- Device tokens never expire but can be revoked

**New table:**
```sql
CREATE TABLE api_keys (
    id UUID PK,
    key_hash VARCHAR(200) NOT NULL UNIQUE,  -- SHA-256 of raw key
    label VARCHAR(100),                     -- "ALPR Gate Camera", "Bay Sensor MQTT"
    scopes TEXT[],                          -- ['tms:read', 'tms:device:write']
    device_id UUID FK device_registry(id),  -- optional link to device
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,                 -- NULL = never
    revoked_at TIMESTAMPTZ,
    created_by UUID FK users(id),
    created_at TIMESTAMPTZ
);

CREATE TABLE audit_events (
    id UUID PK,
    user_id UUID,
    api_key_id UUID,
    action VARCHAR(100) NOT NULL,           -- 'CREATE_CONSIGNMENT', 'OVERRIDE_GATE', etc.
    resource_type VARCHAR(50),
    resource_id UUID,
    payload JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ
);
```

---

### NEW: `device-service` (port 8008)

**Responsibility**: Central registry and health monitor for ALL IoT/hardware devices in the plant. CRUD for devices, health status polling, configuration push, offline alerting.

**Device types managed:**
| Type | Examples |
|---|---|
| ALPR camera | gate_entry_cam, parking_exit_cam |
| LED display | gate_led, parking_exit_led |
| Bay sensor | Milesight EM400-MUD (160 units) |
| K70 bay light | 160 banner lights |
| MQTT gateway | LoRaWAN→MQTT bridge |

**REST API:**
- `GET  /api/v1/devices` — list all devices with health status
- `POST /api/v1/devices` — register new device
- `GET  /api/v1/devices/{id}` — device detail + last heartbeat
- `PUT  /api/v1/devices/{id}` — update config (IP, topic, threshold)
- `DELETE /api/v1/devices/{id}` — decommission
- `GET  /api/v1/devices/{id}/health` — current health (ONLINE/OFFLINE/DEGRADED)
- `POST /api/v1/devices/{id}/test` — send test command (ping LED, test K70 light)
- `GET  /api/v1/devices/health-summary` — dashboard: X online, Y offline
- `GET  /api/v1/devices/{id}/events` — recent event log for this device
- `GET  /api/v1/devices/health` — service health

**Database (tms_devices):**
```sql
CREATE TABLE device_registry (
    id UUID PK,
    name VARCHAR(100) NOT NULL,           -- 'Gate Entry ALPR', 'Bay AR-N1 Sensor'
    type VARCHAR(30) NOT NULL,            -- 'ALPR'|'LED'|'BAY_SENSOR'|'K70_LIGHT'|'MQTT_GW'
    location VARCHAR(100),
    ip_address INET,
    port INT,
    mac_address VARCHAR(20),
    firmware_version VARCHAR(50),
    config JSONB,                         -- device-specific config (topic, threshold, etc.)
    api_key_id UUID FK api_keys(id),      -- scoped API key for this device
    is_active BOOLEAN DEFAULT TRUE,
    commissioned_at TIMESTAMPTZ,
    decommissioned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);

CREATE TABLE device_health_log (
    id UUID PK,
    device_id UUID FK device_registry(id),
    status VARCHAR(20),                   -- 'ONLINE'|'OFFLINE'|'DEGRADED'
    latency_ms INT,
    error_message TEXT,
    checked_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE device_heartbeats (
    device_id UUID PK,                    -- FK device_registry(id)
    last_seen_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20),
    metadata JSONB,
    updated_at TIMESTAMPTZ
);
```

**Background tasks:**
- Health poller: every 60s, HTTP GET to each active device's health endpoint
- Offline alerter: publish `tms.device.offline` if device misses 3 consecutive polls
- MQTT heartbeat listener: bay sensors publish keepalive, device-service marks them ONLINE

---

### NEW: `config-service` (port 8009)

**Responsibility**: Single source of truth for all system configuration variables. Mendix reads/writes config here. All services read their runtime config from this service (with Redis cache, 60s TTL). This eliminates hardcoded thresholds.

**REST API:**
- `GET  /api/v1/config` — all config key-value pairs (grouped by namespace)
- `GET  /api/v1/config/{namespace}` — e.g. `/config/gate`, `/config/bay`, `/config/sms`
- `PUT  /api/v1/config/{namespace}/{key}` — update single config value (admin only)
- `POST /api/v1/config/bulk` — update multiple values
- `GET  /api/v1/config/history/{key}` — change audit trail for a config key
- `GET  /api/v1/config/health`

**Config namespaces:**
```yaml
gate:
  early_arrival_minutes: 60        # threshold to proceed vs hold
  late_arrival_minutes: 30         # after this = reject
  parking_to_bay_call_minutes: 15  # when to call truck to bay
  bay_conflict_adjacent_slots: 2   # check ±N adjacent slots
  sla_parking_max_minutes: 45      # SLA breach if truck in parking > this

bay:
  sensor_distance_threshold_mm: 500     # < this = occupied
  sensor_debounce_count: 3              # N consecutive readings before state flip
  sensor_debounce_interval_seconds: 30  # interval between debounce readings

notification:
  supervisor_phones:                     # list of supervisor numbers for SLA alerts
    - "+919876543210"
  sms_enabled: true
  whatsapp_enabled: false

display:
  gate_led_message_allow: "PROCEED TO PARKING — SLOT: {slot_time}"
  gate_led_message_hold: "WAIT — SUPPLY TIME IN {minutes} MINS"
  gate_led_message_reject: "ENTRY NOT ALLOWED — CONTACT LOGISTICS"
  parking_led_message_call: "TRUCK {plate}: PROCEED TO BAY {bay_code}"
  parking_led_message_wait: "WAIT IN PARKING — YOUR SLOT: {slot_time}"

k70:
  planned_vacant_color: GREEN
  planned_occupied_color: AMBER
  unplanned_occupied_color: RED
  unplanned_vacant_color: OFF
  planned_occupied_mode: BLINK
  unplanned_occupied_mode: SOLID

hardware:
  gate_alpr_ip: "192.168.10.100"
  gate_alpr_nats_subject: "alpr.gate.events"
  parking_exit_alpr_ip: "192.168.10.101"
  parking_exit_alpr_nats_subject: "alpr.parking_exit.events"
  gate_led_ip: "192.168.10.51"
  parking_exit_led_ip: "192.168.10.52"
  k70_gateway_ip: "192.168.10.50"
  mqtt_broker_url: "mqtt://mosquitto:1883"
  mqtt_sensor_topic_pattern: "lorawan/+/up"
```

All services call `GET /api/v1/config/{namespace}` at startup and cache in Redis (key: `config:{namespace}`, TTL 60s). Mendix shows full config UI with validation.

---

## Hardware Topology (Revised)

```
Plant Layout:
                    ┌─────────────────────────────────────────────────┐
                    │                                                   │
  ┌─────────┐  ALPR │  ┌─────────────┐              ┌──────────────┐  │
  │  Vendor │──cam──┼─►│  GATE ENTRY │              │  PARKING     │  │
  │  Truck  │       │  │  LED display│              │  COUNTER     │  │
  └────┬────┘       │  └─────────────┘              │  (material   │  │
       │            │                                │  entry)      │  │
       │            │  ┌──────────────────────────── ┤              │  │
       ▼            │  │      PARKING LOT            └──────────────┘  │
  Gate ALPR sends   │  │   (all trucks wait here)                       │
  alpr.gate.events  │  │                                                │
                    │  └────────────────────────────────────────────── ┤
                    │                                                   │
                    │  ┌──────────────────────────────────────────────┐│
                    │  │              160 DOCK BAYS                    ││
                    │  │  [Bay AR-N1][Bay AR-N2]...[Bay C8]            ││
                    │  │  K70 lights    Milesight sensors              ││
                    │  └──────────────────────────────────────────────┘│
                    │                                                   │
  Parking Exit ─────┼──► ALPR cam → alpr.parking_exit.events           │
  LED display ──────┼──► Shows "THANK YOU" on exit                     │
                    └─────────────────────────────────────────────────-┘
```

**Device counts:**
- 2 ALPR cameras (gate entry + parking exit)
- 2 LED displays (gate + parking exit)
- 1 internal parking display (calls trucks to bays)
- 160 bay sensors (Milesight EM400-MUD via LoRaWAN/MQTT)
- 160 K70 bay lights
- 1 MQTT broker (Mosquitto) for LoRaWAN sensor data

---

## Infrastructure Changes

### New: Mosquitto MQTT Broker

```yaml
# Add to docker-compose.yml
mosquitto:
  image: eclipse-mosquitto:2
  ports:
    - "1883:1883"
    - "9883:9883"    # WebSocket for browser-based monitoring
  volumes:
    - ./infrastructure/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
    - mosquitto_data:/mosquitto/data
```

`mosquitto.conf`:
```
listener 1883
protocol mqtt
allow_anonymous false
password_file /mosquitto/config/passwd

listener 9883
protocol websockets

persistence true
persistence_location /mosquitto/data/
log_type all
```

ALPR cameras publish to NATS directly (they run the NATS SDK or HTTP → NATS proxy). Bay sensors arrive via LoRaWAN gateway → MQTT.

### OpenTelemetry Collector (enterprise)

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:latest
  volumes:
    - ./infrastructure/otel/otel-config.yaml:/etc/otel/config.yaml:ro
  ports:
    - "4317:4317"    # OTLP gRPC
    - "4318:4318"    # OTLP HTTP
```

Each FastAPI service adds `opentelemetry-instrumentation-fastapi` + `opentelemetry-exporter-otlp`. Traces visible in Grafana Tempo.

### Kong API Gateway (replaces Nginx in production)

```yaml
kong:
  image: kong:3.6-alpine
  environment:
    KONG_DATABASE: "off"     # DB-less mode
    KONG_DECLARATIVE_CONFIG: /kong/kong.yml
  ports:
    - "80:8000"
    - "443:8443"
    - "8001:8001"   # Kong Admin API
  volumes:
    - ./infrastructure/kong/kong.yml:/kong/kong.yml:ro
```

Kong provides:
- JWT verification at gateway level (no service-to-service JWT re-validation overhead)
- Rate limiting: `tms:write` endpoints — 100 req/min; `tms:admin` — 20 req/min; device endpoints — 1000 req/min
- IP whitelist for device API keys
- Request/response logging to Prometheus
- mTLS plugin for service-to-service calls

---

## Enterprise API Security Standards

### 1. Authentication layers

| Client type | Auth method | Token lifetime |
|---|---|---|
| Mendix (user) | OAuth2 password → JWT access + refresh | 15min / 7 days |
| Device (ALPR, sensor) | Scoped API key in `X-API-Key` header | Never (revocable) |
| Service-to-service | JWT from auth-service with service account | 24h, auto-renew |
| Public (SMS links) | Signed token in URL (HMAC-SHA256 + expiry) | 24h |

### 2. Authorization scopes

| Scope | What it permits |
|---|---|
| `tms:read` | Read all data |
| `tms:write` | Create/update operational data |
| `tms:admin` | User management, config changes |
| `tms:gate:override` | Manual gate override entries |
| `tms:device:write` | Send commands to hardware devices |
| `tms:config:write` | Update system configuration |

### 3. Endpoint-level security

All write endpoints require:
- Valid JWT or API key
- Appropriate scope
- Rate limit not exceeded
- Request body passes Pydantic strict validation
- Audit log entry written

Special endpoints:
- `POST /gate/manual-entry` — requires `tms:gate:override` scope (supervisor only)
- `PUT /config/{ns}/{key}` — requires `tms:config:write` scope
- `POST /devices/{id}/test` — requires `tms:device:write` scope
- `DELETE /api-keys/{id}` — requires `tms:admin` scope

### 4. Network security

- All external traffic → Kong (TLS termination)
- Internal service-to-service: Docker network isolation, no external ports
- Secrets via Docker secrets or Vault (not environment variables in production)
- Database passwords rotated via Vault dynamic credentials

### 5. Idempotency

All POST/PATCH endpoints accept optional `Idempotency-Key` header:
- Key stored in Redis (TTL 24h)
- Duplicate request returns cached response
- NATS events include `event_id` (UUID) — consumers deduplicate using Redis SET

---

## Updated Service Port Map

| Service | Port | New? |
|---|---|---|
| gate-service | 8001 | Updated |
| bay-service | 8002 | Updated |
| schedule-service | 8003 | Updated |
| vendor-service | 8004 | Minor |
| notification-service | 8005 | Updated |
| display-service | 8006 | Updated |
| auth-service | 8007 | Updated (enterprise) |
| device-service | 8008 | **NEW** |
| config-service | 8009 | **NEW** |
| Kong (API Gateway) | 80/443 | Replaces nginx |
| NATS | 4222 | — |
| PostgreSQL | 5432 | — |
| Redis | 6379 | — |
| MinIO | 9000 | — |
| **Mosquitto MQTT** | **1883** | **NEW** |
| Prometheus | 9090 | — |
| Grafana | 3000 | — |
| **OTel Collector** | **4317** | **NEW** |

---

## Updated NATS Subjects

```
alpr.gate.events                (ALPR gate camera → gate-service)
alpr.parking_exit.events        (ALPR parking exit → gate-service)

tms.gate.truck_at_gate          (gate-service → schedule, bay, notification, display)
tms.gate.truck_at_parking_exit  (gate-service → schedule)
tms.gate.manual_entry           (gate-service → audit)

tms.bay.occupied                (bay-service → schedule, notification, display)
tms.bay.vacated                 (bay-service → schedule, notification, display)
tms.bay.sensor_conflict         (bay-service → device-service, notification)

tms.schedule.call_to_bay        (schedule-service → display, notification)  ← NEW
tms.schedule.consignment_updated
tms.schedule.truck_registered
tms.schedule.sla_breach         (schedule-service → notification, display)  ← NEW

tms.device.offline              (device-service → notification)             ← NEW
tms.device.online               (device-service → notification)             ← NEW

tms.dlq.*                       (dead-letter queue for all failed messages)
```

---

## Mendix Pages (updated)

| Page | Calls |
|---|---|
| Bay Dashboard | `GET /bays/digital-twin` — Andon colors, received qty |
| Gantt Schedule | `GET /schedule/gantt?date=` |
| Parking Queue | `GET /schedule/parking-queue` |
| Truck Journey | `GET /gate/movements/{plate}/timeline` |
| Material Receipt | `PATCH /schedule/consignments/{id}/receipt` |
| **Device Management** | `GET/POST/PUT/DELETE /devices` |
| **System Configuration** | `GET/PUT /config/{namespace}/{key}` |
| **API Key Management** | `GET/POST/DELETE /auth/api-keys` |
| Notification Logs | `GET /notifications/logs` |
| SLA Alerts | `GET /gate/sla-alerts` |
| User Management | `GET/POST/PUT /auth/users` |

---

## Implementation Order (revised)

| Phase | What | Why first |
|---|---|---|
| 0 | Infrastructure: add Mosquitto, OTel Collector, Kong | Unblocks everything |
| 1 | auth-service: OAuth2 scopes, API keys, audit log | Security foundation |
| 2 | config-service | All other services depend on runtime config |
| 3 | device-service | Device registry needed before ALPR/sensor integration |
| 4 | schedule-service: truck_visits, multi-bay, conflict resolution | Core business logic |
| 5 | bay-service: MQTT, debounce, Andon, bay_receipts | IoT integration |
| 6 | gate-service: dual ALPR, Redis fallback, idempotency | Entry flow |
| 7 | display-service: Andon colors, batch lights, 4 displays | Visual feedback |
| 8 | notification-service: new templates, SLA alerts | Alerts |
| 9 | vendor-service: truck-visits view | Self-service |
| 10 | Integration + OpenTelemetry instrumentation | Observability |
| 11 | Mendix pages: Device Mgmt, Config, Journey Timeline | UX |
| 12 | Load test, security pen test, production hardening | Ship |

---

## Critical Files to Modify (on top of what exists)

| File | Change |
|---|---|
| `docker-compose.yml` | Add mosquitto, otel-collector, config-service, device-service, kong |
| `shared/tms_shared/models/events.py` | Add CallToBayEvent, SLABreachEvent, DeviceOfflineEvent |
| `services/gate-service/app/services/gate_logic.py` | Redis fallback, idempotency, dual ALPR routing |
| `services/bay-service/app/services/occupancy.py` | Andon color logic, debounce, MQTT subscriber |
| `services/schedule-service/app/models/consignment.py` | Add truck_visits table, received_qty, material_entry_time |
| `services/schedule-service/app/services/conflict_resolver.py` | **NEW** — bay conflict resolution engine |
| `services/schedule-service/app/services/sla_monitor.py` | **NEW** — background SLA breach checker |
| `services/auth-service/app/models/user.py` | Add api_keys + audit_events tables |
| New: `services/device-service/` | Full new service |
| New: `services/config-service/` | Full new service |
| New: `infrastructure/mosquitto/` | MQTT broker config |
| New: `infrastructure/otel/` | OpenTelemetry collector config |
| New: `infrastructure/kong/` | Kong gateway config |
