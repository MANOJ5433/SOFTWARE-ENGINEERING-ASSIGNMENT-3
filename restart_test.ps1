# Restart and persistence test for the Docker stack.
# Usage (from the project root):  .\scripts\restart_test.ps1
# Records bookings, tickets and the latest audit id, restarts each container in turn, and verifies
# that every record is still present and unchanged after each step.
$ErrorActionPreference = "Stop"
$env:BASE_URL = "http://localhost:8080"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path evidence | Out-Null
$snapshot = "evidence\before-restart.json"

function Verify($label) {
    Write-Host "== Verify after: $label ==" -ForegroundColor Cyan
    python scripts\persistence_check.py verify $snapshot
    if ($LASTEXITCODE -ne 0) { throw "Persistence check FAILED after: $label" }
}

Write-Host "== Baseline snapshot ==" -ForegroundColor Cyan
python scripts\persistence_check.py snapshot $snapshot
if ($LASTEXITCODE -ne 0) { throw "Could not take snapshot; is the stack running?" }

Write-Host "== Restart backend-1 (backend-2 keeps serving) ==" -ForegroundColor Cyan
docker compose restart backend1
Start-Sleep -Seconds 8
Verify "backend-1 restart"

Write-Host "== Restart backend-2 ==" -ForegroundColor Cyan
docker compose restart backend2
Start-Sleep -Seconds 8
Verify "backend-2 restart"

Write-Host "== Restart PostgreSQL container ==" -ForegroundColor Cyan
docker compose restart db
Start-Sleep -Seconds 12
Verify "database restart"

Write-Host "== Stop the whole stack (volumes kept), then start it again ==" -ForegroundColor Cyan
docker compose down
docker compose up -d
Start-Sleep -Seconds 20
Verify "full stack down and up"

Write-Host "ALL PERSISTENCE CHECKS PASSED" -ForegroundColor Green
