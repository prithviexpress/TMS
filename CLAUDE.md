# TMS — Truck Movement System

MSIL (Maruti Suzuki India Limited) plant truck movement management system.
160 dock bays, ALPR cameras, LoRaWAN occupancy sensors, LED displays, Banner K70 bay lights.

## Stack

- **Frontend**: Mendix (external — not in this repo)
- **Backend**: 9 Python 3.12 FastAPI microservices (no Docker — native processes)
- **Infra**: PostgreSQL 16, Memurai (Redis-compatible), NATS 2.10 (JetStream), Mosquitto MQTT, Nginx (reverse proxy + admin portal), Prometheus+Grafana
- **Process mgmt**: Honcho (dev — reads Procfile), NSSM (production Windows Services)
- **OS**: Production = Windows Server 2022. Dev = Windows 10/11 + Git for Windows
- **IoT**: Milesight EM400-MUD sensors via LoRaWAN → MQTT (Mosquitto)

## Commands

Run these from Git Bash (comes with Git for Windows):

```bash
make setup        # create per-service .venv and install deps (first time only)
make up           # start all 9 services via Honcho — Ctrl+C to stop
make down         # kill orphaned uvicorn processes
make logs         # tail NSSM log files (production)
make status       # curl /health on all 9 services
make migrate      # run alembic migrations on all services
make seed         # seed bays + default admin user
make test         # run pytest across all services
make lint         # ruff check all services

# NATS debugging
make nats-streams
make nats-pub SUBJECT=alpr.gate.events MSG='{"plate":"KA01AB1234","direction":"entry","confidence":98.5,"camera_id":"gate","ts":"2026-05-13T10:00:00Z"}'

# NATS streams init (run once after NATS starts)
powershell -File infrastructure/nats/init-streams.ps1
```

## Service ports (all bind to 127.0.0.1 — loopback only)

| Service              | Port |
|----------------------|------|
| gate-service         | 8001 |
| bay-service          | 8002 |
| schedule-service     | 8003 |
| vendor-service       | 8004 |
| notification-service | 8005 |
| display-service      | 8006 |
| auth-service         | 8007 |
| device-service       | 8008 |
| config-service       | 8009 |
| Nginx (API Gateway)  | 80 / 443 |
| NATS                 | 4222 |
| NATS monitoring      | 8222 |
| PostgreSQL           | 5432 |
| Redis                | 6379 |
| Mosquitto MQTT       | 1883 |
| Prometheus           | 9090 |
| Grafana              | 3000 |
| pgAdmin4             | 5050 |
| Admin portal (Nginx) | 8080 |

## Architecture

```
Mendix Frontend
     │ REST + JWT (Bearer)
   Nginx API Gateway (:80)
     │
     ├── /api/v1/gate/          → gate-service:8001
     ├── /api/v1/bays/          → bay-service:8002
     ├── /api/v1/schedule/      → schedule-service:8003
     ├── /api/v1/vendors/       → vendor-service:8004
     ├── /api/v1/notifications/ → notification-service:8005
     ├── /api/v1/display/       → display-service:8006
     ├── /api/v1/auth/          → auth-service:8007
     ├── /api/v1/devices/       → device-service:8008
     └── /api/v1/config/        → config-service:8009

NATS JetStream subjects:
  alpr.gate.events              (ALPR gate camera → gate-service)
  alpr.parking_exit.events      (ALPR parking exit → gate-service)
  tms.gate.truck_at_gate        (gate-service → schedule, display, notification)
  tms.gate.truck_at_parking_exit
  tms.bay.occupied              (bay-service → schedule, notification, display)
  tms.bay.vacated               (bay-service → schedule, notification, display)
  tms.bay.andon_update          (schedule-service → display-service K70 lights)
  tms.schedule.call_to_bay      (schedule-service → display, notification)
  tms.schedule.sla_breach       (schedule-service → notification)
  tms.device.offline            (device-service → notification)
  tms.dlq.*                     (dead-letter queue)

MQTT topics (Mosquitto):
  lorawan/{device_eui}/up       (LoRaWAN sensor → bay-service subscriber)
```

## Service layout (each service)

```
services/<name>/
  pyproject.toml
  alembic.ini
  alembic/versions/
  app/
    main.py         # FastAPI app, lifespan hooks, NATS/MQTT subscriber startup
    config.py       # pydantic-settings Settings class
    database.py     # async SQLAlchemy engine + session factory
    models/         # SQLAlchemy ORM models
    schemas/        # Pydantic request/response schemas
    routers/        # FastAPI APIRouter definitions
    services/       # Business logic
    tests/          # pytest
  .venv/            # per-service virtualenv (not committed)
```

## Shared library

`shared/tms_shared/` — install with `pip install -e ../../shared` inside each service venv.

- `nats_client.py` — async NATS connection factory + JetStream stream initialisation
- `auth.py` — FastAPI JWT dependency (Bearer token verification)
- `models/events.py` — Pydantic schemas for all NATS event payloads (single source of truth)

## Truck lifecycle (v2)

```
Truck arrives at gate → ALPR reads plate → Gate LED: "PROCEED TO PARKING"
  → gate-service logs arrival; all trucks go to parking first
  → Clerk at parking counter does material system (GR) entry via Mendix
  → schedule-service monitors bay availability
  → < 15 mins to slot AND bay vacant → publish tms.schedule.call_to_bay
  → Parking Exit LED: "TRUCK {plate}: PROCEED TO BAY AR-N1"
  → Truck drives to bay; LoRaWAN sensor (via MQTT) confirms occupancy
  → bay-service updates K70 Andon light (GREEN solid = normal unloading)
  → Received qty updated 0 → actual at bay terminal (Mendix)
  → Sensor vacates → truck may have more bays (multi-consignment)
  → All bays done → truck exits via parking exit ALPR
```

## Admin & Developer Web Portal

All admin/dev tools are standalone web pages — not inside Mendix.
Access: `http://tms-admin.msil.local:8080/` (plant IT subnet only + HTTP Basic Auth)

| Tool | URL |
|------|-----|
| Landing page | `:8080/` |
| DB Browser (pgAdmin4) | `:8080/db/` |
| Swagger — any service | `:8080/api/{service}/docs` |
| Grafana | `:8080/grafana/` |
| Prometheus | `:8080/prometheus/` |
| NATS Monitor | `:8080/nats/` |

## Skill routing (gstack)

This project uses [garrytan/gstack](https://github.com/garrytan/gstack) Claude Code skills
(installed at `~/.claude/skills/gstack/`) for AI-assisted development workflows.

- Architecture / design → `/plan-eng-review`
- Code review / diff → `/review`
- QA / test site → `/qa`
- Ship / PR → `/ship`
- Investigate bugs → `/investigate`

## Environment

Copy `.env.example` to `.env` and fill in values before running `make up`.
All production secrets must go through Vault — never in `.env` on production servers.

## Windows Setup

TMS runs natively on Windows. No WSL2, no Docker required.

### One-time infrastructure install

| Component | Download / Install |
|---|---|
| Python 3.12 | python.org/downloads |
| Git for Windows | git-scm.com (includes Git Bash + `make`) |
| PostgreSQL 16 | postgresql.org/download/windows |
| Memurai (Redis) | memurai.com (free tier, Windows-native Redis) |
| NATS 2.10 | nats.io/download → `nats-server.exe`, add to PATH |
| NATS CLI | github.com/nats-io/natscli/releases → `nats.exe`, add to PATH |
| Mosquitto 2 | mosquitto.org/download |
| Nginx | nginx.org/en/docs/windows.html |
| NSSM | nssm.cc/download (production service manager) |
| Honcho | `pip install honcho` (dev process runner) |
| Prometheus | prometheus.io/download |
| Grafana | grafana.com/grafana/download?platform=windows |

### First-time dev setup (Git Bash)

```bash
# 1. Clone repo and set up venvs
git clone <repo>
cd TMS
make setup          # creates .venv + installs deps for all 9 services

# 2. Copy and fill in .env
cp .env.example .env

# 3. Init DB
make migrate
make seed

# 4. Init NATS streams (run once after nats-server.exe starts)
powershell -File infrastructure/nats/init-streams.ps1

# 5. Start all services (Ctrl+C to stop)
make up
```

### Production: register as Windows Services (NSSM)

```powershell
# Run as Administrator
.\infrastructure\nssm\register-services.ps1

# Start / stop all
Get-Service TMS-* | Start-Service
Get-Service TMS-* | Stop-Service
```
