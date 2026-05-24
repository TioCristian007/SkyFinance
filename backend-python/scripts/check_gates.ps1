# check_gates.ps1 — Corre los gates de calidad de Sky manualmente.
# Equivalente PowerShell al hook .githooks/pre-push.
#
# Uso:
#   cd backend-python
#   .\.venv\Scripts\Activate.ps1
#   .\scripts\check_gates.ps1
#
# Saltar gate (emergencia): $env:SKY_SKIP_GATE = "1"

Set-StrictMode -Version Latest

if ($env:SKY_SKIP_GATE -eq "1") {
    Write-Host "[check_gates] SKY_SKIP_GATE=1 → gate OMITIDO" -ForegroundColor Yellow
    exit 0
}

$failed = @()

Write-Host "`n[check_gates] ruff..." -ForegroundColor Cyan
python -m ruff check src/sky/ tests/
if ($LASTEXITCODE -ne 0) { $failed += "ruff" }

Write-Host "`n[check_gates] mypy..." -ForegroundColor Cyan
python -m mypy src/sky/
if ($LASTEXITCODE -ne 0) { $failed += "mypy" }

Write-Host "`n[check_gates] pytest..." -ForegroundColor Cyan
python -m pytest tests/ -q
if ($LASTEXITCODE -ne 0) { $failed += "pytest" }

Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "[check_gates] OK ✓ — todos los gates en verde" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[check_gates] FALLÓ: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
