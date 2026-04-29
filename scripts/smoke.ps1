$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Basetemp = Join-Path ".pytest-tmp" ("smoke-" + $PID)

python -m pytest tests/smoke -q --basetemp=$Basetemp
