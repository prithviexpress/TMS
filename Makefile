.PHONY: up down build logs ps migrate seed test lint shell

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	@for svc in auth-service schedule-service bay-service gate-service display-service notification-service vendor-service; do \
		echo "=== Migrating $$svc ==="; \
		docker compose exec $$svc alembic upgrade head; \
	done

seed:
	docker compose exec schedule-service python -m app.seeds.bays
	docker compose exec auth-service python -m app.seeds.users

test:
	@for svc in auth-service schedule-service bay-service gate-service display-service notification-service vendor-service; do \
		echo "=== Testing $$svc ==="; \
		docker compose exec $$svc python -m pytest app/tests/ -v; \
	done

lint:
	@for svc in auth-service schedule-service bay-service gate-service display-service notification-service vendor-service; do \
		docker compose exec $$svc ruff check app/; \
	done

shell-%:
	docker compose exec $* /bin/bash

nats-streams:
	docker compose exec nats nats stream ls --server nats://localhost:4222

nats-pub:
	@echo "Usage: make nats-pub SUBJECT=alpr.gate_2.events MSG='{\"plate\":\"KA01AB1234\"}'"
	docker compose exec nats nats pub $(SUBJECT) '$(MSG)' --server nats://localhost:4222
