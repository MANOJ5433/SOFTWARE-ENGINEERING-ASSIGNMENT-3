# Runs the functional, concurrency and bounded-load checks against a running stack.
# Usage (from the project root):  .\scripts\run_all_checks.ps1
#                                 .\scripts\run_all_checks.ps1 -BaseUrl http://localhost:8080 -Threads 20 -Seconds 20
param(
    [string]$BaseUrl = "http://localhost:8080",
    [int]$Threads = 20,
    [int]$Seconds = 20
)
$ErrorActionPreference = "Stop"
$env:BASE_URL = $BaseUrl
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== Functional checks ==" -ForegroundColor Cyan
python scripts\test_api.py
if ($LASTEXITCODE -ne 0) { Write-Error "Functional checks FAILED"; exit 1 }

Write-Host "== Concurrency and retry-safety checks ==" -ForegroundColor Cyan
python scripts\concurrency_test.py --threads $Threads
if ($LASTEXITCODE -ne 0) { Write-Error "Concurrency checks FAILED"; exit 1 }

Write-Host "== Bounded load experiment ==" -ForegroundColor Cyan
python scripts\load_test.py --threads $Threads --seconds $Seconds
exit $LASTEXITCODE
