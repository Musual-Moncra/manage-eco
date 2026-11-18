# Build standalone Windows executable: dist\eco.exe
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --upgrade pip
python -m pip install -e . pyinstaller

pyinstaller --noconfirm --clean packaging\eco.spec

$SmokeDb = Join-Path $env:TEMP ("eco_smoke_" + [guid]::NewGuid().ToString("N") + ".db")
try {
    & .\dist\eco.exe --json --db $SmokeDb --today 2026-11-06 income 1000000 salary | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "income smoke test failed" }
    & .\dist\eco.exe --json --db $SmokeDb --today 2026-11-06 dash | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "dash smoke test failed" }
} finally {
    Remove-Item -ErrorAction SilentlyContinue $SmokeDb
}

Write-Host "Build succeeded: $Root\dist\eco.exe" -ForegroundColor Green
