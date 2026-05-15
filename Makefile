.PHONY: up down logs status migrate seed test lint nats-streams nats-pub setup

SERVICES = gate-service schedule-service bay-service vendor-service \
           notification-service display-service auth-service \
           device-service config-service

# ── Dev: start all 9 services via Honcho (reads Procfile, Ctrl+C to stop) ──────
up:
	honcho start

# ── Dev: kill orphaned uvicorn processes ────────────────────────────────────────
down:
	-taskkill /F /IM uvicorn.exe 2>/dev/null; true

# ── Prod: tail NSSM log files ───────────────────────────────────────────────────
logs:
	tail -f logs/*.log

# ── Health-check every service via /health endpoint ─────────────────────────────
status:
	@for svc_port in gate:8001 bay:8002 schedule:8003 vendor:8004 notification:8005 display:8006 auth:8007 device:8008 config:8009; do \
		name=$$(echo $$svc_port | cut -d: -f1); \
		port=$$(echo $$svc_port | cut -d: -f2); \
		printf "%-20s" "$$name ($$port):"; \
		curl -sf http://127.0.0.1:$$port/health 2>/dev/null \
		  | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null \
		  || echo "DOWN"; \
	done

# ── Alembic migrations ───────────────────────────────────────────────────────────
migrate:
	@for svc in $(SERVICES); do \
		echo "=== Migrating $$svc ==="; \
		(cd services/$$svc && .venv/Scripts/alembic upgrade head); \
	done

# ── Seed: bays + default admin user ─────────────────────────────────────────────
seed:
	(cd services/schedule-service && .venv/Scripts/python -m app.seeds.bays)
	(cd services/auth-service     && .venv/Scripts/python -m app.seeds.users)

# ── Tests ────────────────────────────────────────────────────────────────────────
test:
	@for svc in $(SERVICES); do \
		echo "=== Testing $$svc ==="; \
		(cd services/$$svc && .venv/Scripts/pytest app/tests/ -v); \
	done

# ── Lint ─────────────────────────────────────────────────────────────────────────
lint:
	@for svc in $(SERVICES); do \
		echo "=== Linting $$svc ==="; \
		(cd services/$$svc && .venv/Scripts/ruff check app/); \
	done

# ── NATS debugging ───────────────────────────────────────────────────────────────
nats-streams:
	nats stream ls --server nats://localhost:4222

nats-pub:
	nats pub $(SUBJECT) "$(MSG)" --server nats://localhost:4222

# ── First-time setup: create per-service venvs and install deps ──────────────────
setup:
	@for svc in $(SERVICES); do \
		echo "=== Setting up $$svc ==="; \
		(cd services/$$svc && python -m venv .venv && .venv/Scripts/pip install -e . -e ../../shared -q); \
	done
