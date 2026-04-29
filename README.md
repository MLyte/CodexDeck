# CodexDeck

[![tests](https://github.com/MLyte/CodexDeck/actions/workflows/tests.yml/badge.svg)](https://github.com/MLyte/CodexDeck/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Windows and Ubuntu](https://img.shields.io/badge/platform-Windows%20%7C%20Ubuntu-informational)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

CodexDeck is a local terminal cockpit for running Codex against an `AI_TODO.md` plan.

It keeps the plan, live output, status, and run controls in one terminal screen so you can guide a local Codex run without leaving the project folder.

The footer shows the resolved package version and the MIT license label.

![CodexDeck terminal UI screenshot](docs/codexdeck-tui.png)

## Why CodexDeck?

- Keeps `AI_TODO.md` visible while Codex works.
- Starts and stops one Codex process safely.
- Streams output live and writes local logs.
- Supports configurable model, permission, and fast-mode placeholders.
- Runs from any folder with the `codexdeck` command after installation.

## Install

Recommended with `pipx`:

```bash
pipx install git+https://github.com/MLyte/CodexDeck.git
codexdeck --version
```

### Quick installation guide

From release source (latest public):

```bash
pipx install git+https://github.com/MLyte/CodexDeck.git
codexdeck --version
```

```powershell
pipx install git+https://github.com/MLyte/CodexDeck.git
codexdeck --version
```

From a local checkout (after edits):

```bash
git clone https://github.com/MLyte/CodexDeck.git
cd CodexDeck
UV_CACHE_DIR=/tmp/uv-cache uv build
pipx install --force dist/codexdeck-*.whl
hash -r
codexdeck --version
```

```powershell
git clone https://github.com/MLyte/CodexDeck.git
Set-Location CodexDeck
$env:UV_CACHE_DIR = if ($env:TEMP) { Join-Path $env:TEMP "uv-cache" } else { "C:\\Temp\\uv-cache" }
uv build
$wheel = Get-ChildItem dist\codexdeck-*.whl | Sort-Object Name | Select-Object -Last 1
pipx install --force $wheel.FullName
codexdeck --version
```

One-shot for iterative development (build + install):

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

```powershell
$root = git rev-parse --show-toplevel
Set-Location $root
if (-not $env:UV_CACHE_DIR) {
  $env:UV_CACHE_DIR = if ($env:TEMP) { Join-Path $env:TEMP "uv-cache" } else { "C:\\Temp\\uv-cache" }
}
uv build
$wheel = Get-ChildItem dist\codexdeck-*.whl | Sort-Object Name | Select-Object -Last 1
if (-not $wheel) { throw "No wheel found in dist\\" }
pipx install --force $wheel.FullName
codexdeck --version
```

How to update to the latest release:

```bash
git fetch --tags --force
LATEST_TAG="$(git tag --sort=-v:refname | grep '^v[0-9]' | head -n 1)"
pipx install --force "git+https://github.com/MLyte/CodexDeck.git@${LATEST_TAG}"
codexdeck --version
```

```powershell
git fetch --tags --force
$latestTag = (git tag --sort=-v:refname | Where-Object { $_ -match '^v[0-9]' } | Select-Object -First 1)
if (-not $latestTag) { throw "No v* tag found" }
pipx install --force "git+https://github.com/MLyte/CodexDeck.git@${latestTag}"
codexdeck --version
```

Development install from a clone:

```bash
git clone https://github.com/MLyte/CodexDeck.git
cd CodexDeck
python -m pip install -e ".[dev]"
codexdeck --print-config
```

`codexdeck` uses the directory where you launch it as the project root. By default it reads `AI_TODO.md`, `codexdeck.conf`, and `logs/` from that folder.

## Quickstart

Ubuntu:

```bash
mkdir my-codex-work
cd my-codex-work
printf '# Plan\n- [ ] Inspect the project\n' > AI_TODO.md
codexdeck
```

Windows PowerShell:

```powershell
mkdir my-codex-work
cd my-codex-work
"# Plan`n- [ ] Inspect the project" | Set-Content AI_TODO.md
codexdeck
```

Print the resolved configuration:

```bash
codexdeck --print-config
```

## Try Without Codex

From a source checkout, you can run CodexDeck with the bundled stub instead of the real Codex CLI.

Ubuntu:

```bash
CODEX_CMD="python3 tests/stubs/codex_stub.py --mode success {todo}" python -m codexdeck
```

Windows PowerShell:

```powershell
$env:CODEX_CMD="python tests/stubs/codex_stub.py --mode success {todo}"
python -m codexdeck
```

## Basic Usage

| Key | Action |
| --- | --- |
| `r` | Run Codex on the current plan |
| `s` | Stop the active run |
| `q` | Quit, with confirmation |
| `e` | Edit `AI_TODO.md` |
| `n` | Add a new task |
| `m` | Cycle model labels |
| `f` | Toggle fast mode |
| `p` | Cycle permission labels |
| `o` | Toggle automatic mode |
| `h` or `?` | Toggle help |
| Arrows / Page Up / Page Down | Scroll the task list |

## Configuration

CodexDeck reads `codexdeck.conf` from the launch folder when present, then applies environment variable overrides.

Minimal example:

```text
CODEX_CMD=codex exec --model {model} "Read {todo}. Work on the first unchecked task only."
CODEX_MODELS=gpt-5.5,gpt-5.4-mini
CODEX_PERMISSIONS=read-only,workspace-write
```

Supported command placeholders include `{todo}`, `{model}`, `{permission}`, and `{fast}`.

See [docs/configuration.md](docs/configuration.md) for the full reference.

## Documentation

- [Usage guide](docs/usage.md)
- [Configuration reference](docs/configuration.md)
- [Development guide](docs/development.md)
- [Build + pipx release guide](docs/pipx-release.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## Project Status

CodexDeck is an early usable MVP. The current focus is packaging, cross-platform terminal validation, documentation polish, and keeping the local workflow boring in the best possible way.

## License

CodexDeck is released under the [MIT License](LICENSE).
