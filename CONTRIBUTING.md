# Contributing

Thanks for helping improve CodexDeck.

## Setup

```bash
git clone https://github.com/MLyte/CodexDeck.git
cd CodexDeck
python -m pip install -e ".[dev]"
```

## Tests

```bash
python -m pytest -q
```

Windows helper scripts are also available:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
```

Tests must not depend on the real Codex CLI. Use `tests/stubs/codex_stub.py` for smoke coverage.

## Pull Requests

- Keep changes focused.
- Include tests for behavior changes.
- Update docs when user-facing commands or configuration change.
- Add screenshots for visible TUI changes when practical.

