# Build + Release Guide (pipx) with auto versioning

This guide documents the current recommended flow for packaging and deploying `codexdeck` with `pipx`, while keeping versioning consistent across release artifacts.

## 1) Prerequisites

From repo root:

- Python 3.10+
- `uv` (for build) or `python -m pip`
- `git`
- `pipx`

```bash
python -m pip install --upgrade pip pipx uv
```

## 2) Auto-versioning (recommended)

Use this one-shot command to bump the patch version from the `pyproject.toml` value:

```bash
python - <<'PY'
import re
from pathlib import Path

files = [
    Path("pyproject.toml"),
    Path("codexdeck.py"),
]

def bump_patch(version: str) -> str:
    major, minor, patch = map(int, version.split("."))
    return f"{major}.{minor}.{patch + 1}"

text = files[0].read_text(encoding="utf-8")
match = re.search(r'(?m)^version\s*=\s*"(\\d+\\.\\d+\\.\\d+)"', text)
if not match:
    raise SystemExit("project version not found in pyproject.toml")

current = match.group(1)
next_version = bump_patch(current)

for path in files:
    if not path.exists():
        continue
    raw = path.read_text(encoding="utf-8")
    updated = re.sub(r'"(\\d+\\.\\d+\\.\\d+)"', f'"{next_version}"', raw, count=1)
    path.write_text(updated, encoding="utf-8")

print(f"version bumped: {current} -> {next_version}")
print(next_version)
PY
```

Recommended options:
- `--bump patch` (default): `x.y.z -> x.y.(z+1)`
- `--bump minor` / `--bump major` is not included in the inline command; keep the one-shot command for manual reviews or add a small script when you need a custom bump policy.

After bumping:

- Update `CHANGELOG.md` with a release section for the new version.
- Validate that `codexdeck --version` prints the expected version.
- Commit the versioned files (`pyproject.toml`, `codexdeck.py`, `CHANGELOG.md`, optional release notes).

> `codexdeck.py` contains a compatibility `__version__` constant and is still used by some entry path; keep it aligned with `pyproject.toml`.

## 3) Build the wheel

```bash
rm -rf dist
UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv build
ls -1 dist/codexdeck-*.whl
```

The built wheel filename should match the bumped version and can be installed by `pipx`.

### One-shot build + pipx install (Linux / WSL)

```bash
(
  cd "$(git rev-parse --show-toplevel)"
  UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv build
  WHEEL_PATH="$(ls dist/codexdeck-*.whl | sort | tail -n 1)"
  pipx install --force "$WHEEL_PATH"
  hash -r
  codexdeck --version
)
```

Use this when you want: bump version -> build -> install in one go.
Use the script instead (`./scripts/setup-codexdeck-pipx.sh --inspect-logs`) when you want version + install + post-install checks in one shot.

### One-shot build + pipx install (Windows / PowerShell)

```powershell
$root = git rev-parse --show-toplevel
Set-Location $root
if (-not $env:UV_CACHE_DIR) {
  $env:UV_CACHE_DIR = if ($env:TEMP) { Join-Path $env:TEMP "uv-cache" } else { "C:\\Temp\\uv-cache" }
}
uv build
$wheel = Get-ChildItem dist\codexdeck-*.whl | Sort-Object Name | Select-Object -Last 1
if (-not $wheel) { throw "No wheel found in dist\\." }
pipx install --force $wheel.FullName
if (Get-Command hash -ErrorAction SilentlyContinue) { hash -r } else { $env:Path = [Environment]::GetEnvironmentVariable("PATH","Process") }
codexdeck --version
```

### One-shot diagnostics for logs (Linux / WSL)

```bash
./scripts/setup-codexdeck-pipx.sh --auto --inspect-logs
tail -n 40 logs/agent.log
tail -n 40 logs/user.log

# to stream:
./scripts/setup-codexdeck-pipx.sh --auto --follow-logs
```

### One-shot diagnostics for logs (Windows / PowerShell)

```powershell
bash scripts/setup-codexdeck-pipx.sh --auto --inspect-logs
Get-Content -Path logs/agent.log -Tail 40
Get-Content -Path logs/user.log -Tail 40
bash scripts/setup-codexdeck-pipx.sh --auto --follow-logs
```

## 4) Deploy locally with pipx

```bash
export XDG_STATE_HOME=/tmp/pipx-state
export PIPX_HOME=/tmp/pipx-home
export PIPX_BIN_DIR=/tmp/pipx-bin
mkdir -p "$XDG_STATE_HOME" "$PIPX_HOME" "$PIPX_BIN_DIR"
export PATH="$PIPX_BIN_DIR:$PATH"

WHEEL_PATH=$(ls dist/codexdeck-*.whl | sort | tail -n 1)
pipx install --force "$WHEEL_PATH"
hash -r
codexdeck --version
```

To redeploy after changing code:

```bash
rm -rf dist
UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv build
pipx install --force dist/codexdeck-*.whl
```

## 5) Deployment from git (CI-like / remote)

From a tagged release:

```bash
pipx install --force git+https://github.com/MLyte/CodexDeck.git@v$(git describe --tags --abbrev=0 | sed 's/^v//')
```

In practice, pin to the target tag explicitly:

```bash
pipx install --force git+https://github.com/MLyte/CodexDeck.git@v0.1.2
```

## 6) How to update to the latest release

From Linux/macOS/WSL:

```bash
./scripts/setup-codexdeck-pipx.sh --git-latest
```

From PowerShell:

```powershell
bash scripts/setup-codexdeck-pipx.sh --git-latest
```

To pin a specific release:

```bash
./scripts/setup-codexdeck-pipx.sh --git-latest --tag v0.1.2
```

```powershell
bash scripts/setup-codexdeck-pipx.sh --git-latest --tag v0.1.2
```

## 7) Pre-flight checks before pipx install

From repo root:

```bash
python -m pytest -q
python -m pytest tests/smoke -q
python -m codexdeck --print-config
python -m pip install dist/codexdeck-*.whl
python -m pip uninstall -y codexdeck >/dev/null || true
```

Then:

```bash
python -m pytest -q
```

## 8) Rollback

If a bad release reaches users:

```bash
pipx uninstall codexdeck
git checkout -- pyproject.toml codexdeck.py CHANGELOG.md
pipx install --force git+https://github.com/MLyte/CodexDeck.git@v<previous_tag>
```

## 9) Common failures

- `No matching distribution found`
  - Check you are targeting an existing tag and the same Python version.
- `pipx install` keeps old binary
  - Ensure `--force` is used and the `PIPX_BIN_DIR` is first in `PATH`.
- `dist/codexdeck-*.whl` not found
  - Re-run `uv build` from repository root and verify `dist/` content.
- `codexdeck --version` mismatch
  - Validate `pyproject.toml`, `codexdeck.py`, and git tag were bumped to the same value before building.
