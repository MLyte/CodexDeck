# Development Guide

## Setup

```bash
python -m pip install -e ".[dev]"
```

This installs the `codexdeck` console command in editable mode.

## Project Layout

- `src/codexdeck/cli.py`: command-line parser and console entrypoint.
- `src/codexdeck/app.py`: terminal application loop.
- `src/codexdeck/core.py`: config, TODO parsing, command construction, state primitives.
- `src/codexdeck/runner.py`: subprocess lifecycle and logs.
- `src/codexdeck/ui.py`: terminal frame rendering.
- `tests/stubs/codex_stub.py`: local Codex substitute for tests.

Root-level `codexdeck.py`, `agent-cockpit.py`, `codexdeck_core.py`, `codexdeck_runner.py`, and `codexdeck_ui.py` are compatibility wrappers for older local workflows.

## Tests

```bash
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest tests/smoke -q
python -m pytest -q
```

The integration suite includes a temporary install check that verifies `codexdeck --print-config` resolves paths from the launch directory, not the repository root.

## Release Checklist

- CI is green on Windows and Ubuntu.
- README screenshot is current.
- `CHANGELOG.md` includes the release notes.
- `codexdeck --version` matches the release tag.
- No tests require the real Codex CLI.
- Version bump and wheel install flow follows `docs/pipx-release.md` (patch auto-bump + build + pipx).
