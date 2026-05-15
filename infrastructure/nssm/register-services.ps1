# register-services.ps1 — Register all 9 TMS services as Windows Services via NSSM.
#
# Run ONCE as Administrator from the TMS root directory:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\infrastructure\nssm\register-services.ps1
#
# Requires: nssm.exe in PATH — download from https://nssm.cc/download
#           All service venvs already created via: make setup

$ErrorActionPreference = "Stop"
$TmsRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path "$TmsRoot\logs" | Out-Null

$Services = @(
    @{ Name = "TMS-gate";         Dir = "services\gate-service";         Port = 8001 },
    @{ Name = "TMS-bay";          Dir = "services\bay-service";          Port = 8002 },
    @{ Name = "TMS-schedule";     Dir = "services\schedule-service";     Port = 8003 },
    @{ Name = "TMS-vendor";       Dir = "services\vendor-service";       Port = 8004 },
    @{ Name = "TMS-notification"; Dir = "services\notification-service"; Port = 8005 },
    @{ Name = "TMS-display";      Dir = "services\display-service";      Port = 8006 },
    @{ Name = "TMS-auth";         Dir = "services\auth-service";         Port = 8007 },
    @{ Name = "TMS-device";       Dir = "services\device-service";       Port = 8008 },
    @{ Name = "TMS-config";       Dir = "services\config-service";       Port = 8009 }
)

foreach ($svc in $Services) {
    $svcDir  = Join-Path $TmsRoot $svc.Dir
    $uvicorn = Join-Path $svcDir ".venv\Scripts\uvicorn.exe"
    $args    = "app.main:app --host 127.0.0.1 --port $($svc.Port)"
    $stdout  = Join-Path $TmsRoot "logs\$($svc.Name).log"
    $stderr  = Join-Path $TmsRoot "logs\$($svc.Name)-error.log"

    Write-Host "Registering $($svc.Name)..."
    nssm install   $svc.Name $uvicorn $args
    nssm set       $svc.Name AppDirectory  $svcDir
    nssm set       $svc.Name AppStdout     $stdout
    nssm set       $svc.Name AppStderr     $stderr
    nssm set       $svc.Name AppRotateFiles 1
    nssm set       $svc.Name AppRotateSeconds 86400
    nssm set       $svc.Name Start SERVICE_AUTO_START
    Write-Host "  $($svc.Name) registered on port $($svc.Port)."
}

Write-Host ""
Write-Host "Registration complete. To start all services:"
Write-Host "  Get-Service TMS-* | Start-Service"
Write-Host "To stop all:"
Write-Host "  Get-Service TMS-* | Stop-Service"
Write-Host "To unregister (run as Administrator):"
Write-Host "  Get-Service TMS-* | ForEach-Object { nssm remove `$_.Name confirm }"
