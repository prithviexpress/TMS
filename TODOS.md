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

## TODO-2: Nginx rate-limit tuning + TLS termination config

**What:** Once all 9 services are stable, tune `infrastructure/nginx/conf.d/tms.conf`
rate-limit burst values from current conservative defaults and add a TLS-terminating
server block for production (`listen 443 ssl`).

**Why:** Current burst values (api:30, sensor:200, auth:10) are estimates. Real traffic
profiling at the plant may show that legitimate ALPR bursts during a gate-open event
exceed 200 req/min, or that the Mendix polling load requires a higher `api` burst.
TLS config is needed before going live — plant IT requires HTTPS for all external traffic.

**Pros:** No code changes — pure Nginx config. `nginx -t` validates before reload.
Rate limits protect MSG91/Twilio SMS budget from runaway clients.

**Cons:** Rate-limit misconfigurations silently drop requests (HTTP 503) — must test
with `wrk` or `locust` before applying to production.

**Context:** TLS certificate: use Let's Encrypt (if internet-accessible) or plant CA.
Add `ssl_certificate` + `ssl_certificate_key` directives to the production server block.
Tune burst with load test: `wrk -t4 -c50 -d30s http://localhost/api/v1/bays`.
Target delivery: Phase 13 (Load test + production hardening).

**Depends on:** All 9 services deployed and stable; plant CA or Let's Encrypt cert issued.

---
