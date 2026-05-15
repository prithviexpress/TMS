# init-streams.ps1 — Create TMS JetStream streams after NATS is ready.
# Run once after NATS starts: .\infrastructure\nats\init-streams.ps1
#
# Requires: nats CLI (nats.exe) in PATH — download from https://nats.io/download/

$ErrorActionPreference = "Stop"
$NATS_URL = "nats://localhost:4222"

# ── Wait for NATS ──────────────────────────────────────────────────────────────
Write-Host "Waiting for NATS server at $NATS_URL ..."
$attempts = 0
while ($attempts -lt 30) {
    $null = nats server check --server $NATS_URL 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    Write-Host "  NATS not ready, retrying in 2 s..."
    Start-Sleep 2
    $attempts++
}
if ($attempts -eq 30) { Write-Error "NATS did not become ready after 60 s"; exit 1 }
Write-Host "NATS is ready."

# ── Helper: create stream, edit if already exists ─────────────────────────────
function Ensure-Stream {
    param(
        [string]$Name,
        [string]$Subjects,
        [string]$MaxAge
    )
    Write-Host "Ensuring stream $Name (subjects: $Subjects, max-age: $MaxAge)..."
    $created = nats stream add $Name `
        --server $NATS_URL `
        --subjects $Subjects `
        --storage file `
        --retention limits `
        --max-age $MaxAge `
        --replicas 1 `
        --discard old `
        --defaults 2>&1
    if ($LASTEXITCODE -ne 0) {
        # Stream exists — update it
        $null = nats stream edit $Name `
            --server $NATS_URL `
            --subjects $Subjects `
            --max-age $MaxAge 2>&1
    }
    Write-Host "  Stream $Name OK."
}

# ── TMS JetStream streams ─────────────────────────────────────────────────────
Ensure-Stream "TMS_GATE"     "tms.gate.*,alpr.>" "168h"   # 7 days
Ensure-Stream "TMS_BAY"      "tms.bay.*"          "168h"
Ensure-Stream "TMS_SCHEDULE" "tms.schedule.*"     "168h"
Ensure-Stream "TMS_VENDOR"   "tms.vendor.*"       "168h"
Ensure-Stream "TMS_DLQ"      "tms.dlq.*"          "720h"   # 30 days

Write-Host ""
Write-Host "All NATS JetStream streams initialized successfully."
