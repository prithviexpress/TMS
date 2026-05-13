# TMS — Truck Movement System

MSIL (Maruti Suzuki India Limited) plant truck movement management system.
160 dock bays, ALPR cameras, LoRaWAN occupancy sensors, LED displays, Banner K70 bay lights.

## Stack

- **Frontend**: Mendix (external — not in this repo)
- **Backend**: 7 Python 3.12 FastAPI microservices
- **Infra**: PostgreSQL 16, Redis 7, NATS 2.10 (JetStream), MinIO, Nginx, Prometheus+Grafana
- **IoT**: Milesight EM400-MUD sensors via LoRaWAN/Chirpstack

## Commands

```bash
make up           # start all services
make down         # stop all services
make build        # rebuild docker images
make logs         # tail all logs
make migrate      # run alembic migrations on all services
make seed         # seed bays + default admin user
make test         # run pytest across all services
make lint         # ruff check all services

# NATS debugging
make nats-streams
make nats-pub SUBJECT=alpr.gate_2.events MSG='{"plate":"KA01AB1234","direction":"entry","confidence":98.5,"camera_id":"gate_2","ts":"2026-05-13T10:00:00Z"}'
```

## Service ports

| Service             | Port |
|---------------------|------|
| gate-service        | 8001 |
| bay-service         | 8002 |
| schedule-service    | 8003 |
| vendor-service      | 8004 |
| notification-service| 8005 |
| display-service     | 8006 |
| auth-service        | 8007 |
| API Gateway (nginx) |   80 |
| NATS                | 4222 |
| NATS monitoring     | 8222 |
| PostgreSQL          | 5432 |
| Redis               | 6379 |
| MinIO               | 9000 |
| MinIO console       | 9001 |
| Prometheus          | 9090 |
| Grafana             | 3000 |

## Architecture

```
Mendix Frontend
     │ REST + JWT
   Nginx (API Gateway :80)
     │
     ├── /api/v1/gate/      → gate-service:8001
     ├── /api/v1/bays/      → bay-service:8002
     ├── /api/v1/schedule/  → schedule-service:8003
     ├── /api/v1/vendors/   → vendor-service:8004
     ├── /api/v1/notifications/ → notification-service:8005
     ├── /api/v1/display/   → display-service:8006
     └── /api/v1/auth/      → auth-service:8007

NATS JetStream subjects:
  alpr.gate_2.events          (ALPR camera → gate-service)
  alpr.parking_exit.events    (parking exit camera → gate-service)
  tms.gate.truck_arrived      (gate-service → bay, schedule, notification, display)
  tms.gate.truck_departed     (gate-service → schedule)
  tms.bay.occupied            (bay-service → schedule, notification, display)
  tms.bay.vacated             (bay-service → schedule, notification, display)
  tms.schedule.consignment_updated
  tms.schedule.truck_registered
```

## Service layout (each service)

```
services/<name>/
  Dockerfile
  pyproject.toml
  alembic.ini
  alembic/versions/
  app/
    main.py         # FastAPI app, lifespan hooks, NATS subscriber startup
    config.py       # pydantic-settings Settings class
    database.py     # async SQLAlchemy engine + session factory
    models/         # SQLAlchemy ORM models
    schemas/        # Pydantic request/response schemas
    routers/        # FastAPI APIRouter definitions
    services/       # Business logic
    tests/          # pytest
```

## Shared library

`shared/tms_shared/` — install with `pip install -e ./shared` inside each service image.

- `nats_client.py` — async NATS connection factory + JetStream stream initialisation
- `auth.py` — FastAPI JWT dependency (Bearer token verification)
- `models/events.py` — Pydantic schemas for all NATS event payloads (single source of truth)

## Truck lifecycle

```
Vendor receives Nagare (production schedule)
  → Vendor registers truck plate + driver phone via Mendix
  → Truck arrives at MSIL gate (ALPR detects plate)
  → gate-service checks: is arrival within 1 hr of Nagare slot?
      YES → is bay vacant?
               YES → allow: LED shows "PROCEED TO BAY AR-N1", K70 light → GREEN
               NO  → Mumbai Trip: LED shows "RETURN — CONTACT LOGISTICS"
      NO  → hold: LED shows "WAIT IN PARKING"
  → bay-service: LoRaWAN sensor confirms truck in bay → publishes tms.bay.occupied
  → notification-service: SMS vendor "Unloading started at AR-N1"
  → bay-service: sensor detects empty → tms.bay.vacated
  → notification-service: SMS "Truck may depart"
  → gate-service: ALPR detects departure → tms.gate.truck_departed
```

## Skill routing (gstack)

This project includes gstack skills in `.claude/skills/gstack/`.

- Architecture / design → `/plan-eng-review`
- Code review / diff → `/review`  
- QA / test site → `/qa`
- Ship / PR → `/ship`
- Investigate bugs → `/investigate`

## Environment

Copy `.env.example` to `.env` and fill in values before running `make up`.
