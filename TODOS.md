# TMS TODOS

Items captured during /plan-eng-review on 2026-05-13.

---

## TODO-1: Andon diff-state Redis flush recovery runbook + test

**What:** Document and test the recovery path when Redis is flushed/restarted: all
`andon:{bay_code}:state` keys are lost, so the diff-based Andon updater will publish
all 160 K70 light updates on the next 60s cycle. Write a 1-page runbook and add a
unit test in `test_sla_monitor.py` that asserts all 160 bays are published after
Redis key eviction.

**Why:** Without documentation, an operator issuing `FLUSHALL` for an unrelated reason
will see all 160 bay lights go to wrong states and not know to wait 61 seconds for the
self-correction. The diff-based design's invariant is invisible without this runbook.

**Pros:** Zero new implementation; the recovery behavior already exists. Runbook + test
makes the invariant explicit and testable.

**Cons:** Low-probability event; K70 lights self-correct within 60s anyway.

**Context:** `andon:{bay_code}:state` keys have no TTL — they are permanent diff markers.
A FLUSHALL triggers a full 160-light resync on the next schedule-service SLA monitor
cycle. Operator runbook should live at `docs/operations/redis-flush-recovery.md`.
Add test to `services/schedule-service/app/tests/test_sla_monitor.py`.

**Depends on:** `services/schedule-service/app/services/sla_monitor.py` being built.

---

## TODO-2: Kong DB-less declarative config (kong.yml)

**What:** Write `infrastructure/kong/kong.yml` that registers all 9 services as Kong
upstreams, adds rate limiting plugins, and enables JWT verification at the gateway layer.

**Why:** Without the declarative config, Kong passes all traffic through with no auth
and no rate limiting — a security gap in production. Every port/endpoint change currently
requires manual Kong Admin API calls. kong.yml makes the gateway infra-as-code.

**Pros:** Infra-as-code; enables rate limiting to protect MSG91/Twilio SMS budget;
allows Kong to do JWT verification so internal services trust forwarded claims.

**Cons:** Kong config changes require a `kong reload` (supervisord SIGHUP) — slight
ops overhead vs just restarting a service.

**Context:** Kong DB-less declarative mode requires `kong.yml` at startup (set via
`KONG_DECLARATIVE_CONFIG` env var). Without it, Kong starts in passthrough mode.
Target delivery: Phase 8 (Integration & Hardening), after all 9 services are stable
on their port assignments.

**Depends on:** All 9 services deployed and stable.

---
