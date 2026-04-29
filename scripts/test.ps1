$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Basetemp = Join-Path ".pytest-tmp" ("test-" + $PID)

python -m pytest -q --basetemp=$Basetemp

$tracked = git ls-files
$secretPattern = "(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['""]?[^'""\s]+"
foreach ($file in $tracked) {
    if ($file -like "logs/*") { continue }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
    $match = Select-String -LiteralPath $file -Pattern $secretPattern -Quiet
    if ($match) {
        Write-Error "Potential secret found in tracked file: $file"
    }
}
