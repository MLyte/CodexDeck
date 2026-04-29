# CodexDeck

CodexDeck is a local terminal cockpit for running one Codex process against an
`AI_TODO.md` file.

It is not an autonomous backlog manager yet. Today it reads the TODO file,
shows the open tasks, starts/stops a single Codex command, streams output, and
writes logs. CodexDeck does not mark tasks done, edit `AI_TODO.md`, generate a
run summary, or manage multiple agents.

## Current State

What works now:

- TUI with two panes: `AI_TODO.md` tasks on the left, Codex output on the right.
- Bottom status bar with state, model, last run, uptime/duration, errors, and a short activity message.
- Compact mode when the terminal is smaller than 80 columns or 20 rows.
- First unchecked task is highlighted as the current target when a run starts.
- Missing TODO file guidance, with `n` to create a starter `AI_TODO.md`.
- Manual and automatic TODO reload based on file modification time.
- One child process at a time, with start/stop/run-timeout handling.
- Live in-memory logs plus persistent append logs in `logs/agent.log`.
- Testable core, runner, parser, and renderer without the real `codex` binary.

Current stance:

- README and user-facing TUI copy should stay English-only.
- `AI_TODO.md` is still the project backlog and may contain older implementation notes.
- The current layout is vertical split left/right. Horizontal layouts and run summaries are not implemented.

## Quick Start

Requirement: Python 3.9+.

Install test dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the app:

```bash
python3 -m codexdeck
```

Print resolved configuration:

```bash
python3 -m codexdeck --print-config
```

Compatibility entrypoints:

```bash
python3 codexdeck.py
python3 agent-cockpit.py
```

## Controls

- `r`: run Codex on the current `AI_TODO.md`.
- `s`: stop the active process.
- `l`: reload `AI_TODO.md`.
- `n`: create a starter `AI_TODO.md` when it is missing.
- `h` or `?`: toggle help.
- `j` / `k`, arrow up/down: scroll tasks.
- `Page Up` / `Page Down`: scroll tasks by one visible page.
- `q`: quit.

`r` starts only if `AI_TODO.md` exists and contains at least one unchecked task.
The process still receives the whole TODO file path, not only the highlighted task.

## Configuration

CodexDeck reads `codexdeck.conf` from the project root when present, then applies
environment variable overrides. The config file format is one `KEY=VALUE` pair
per line. Empty lines and `#` comments are ignored.

Supported settings:

- `CODEX_CMD`: command used to start Codex. Default: `codex {todo}`.
- `CODEX_MODEL`: model label shown in the status bar. Default: `normal`.
- `RUN_TIMEOUT_SECONDS`: maximum run duration before controlled stop. Default: `3600`.
- `STOP_TIMEOUT_SECONDS`: delay before escalating stop handling. Default: `5`.
- `STATE_REFRESH_HZ`: target UI refresh rate. Default: `8`.
- `MAX_LOG_LINES`: max log lines kept in memory. Default: `5000`.
- `CODEX_TODO_PATH` or `TODO_PATH`: TODO path. Default: `AI_TODO.md`.
- `CODEX_LOG_PATH` or `LOG_PATH`: persistent log path. Default: `logs/agent.log`.
- `CODEX_CONFIG_PATH`: config file path other than `codexdeck.conf`.
- `CODEX_ASCII_BORDERS=1`: force ASCII borders for terminals with poor Unicode support.

Example `codexdeck.conf`:

```text
CODEX_CMD=python3 tests/stubs/codex_stub.py --mode success {todo}
CODEX_MODEL=stub
MAX_LOG_LINES=200
```

Stub run without the real Codex CLI:

```bash
CODEX_CMD="python3 tests/stubs/codex_stub.py --mode success {todo}" python3 -m codexdeck
```

PowerShell equivalent:

```powershell
$env:CODEX_CMD="python tests/stubs/codex_stub.py --mode success {todo}"
python -m codexdeck
```

## Architecture

Current file roles:

- `codexdeck.py`: official `python -m codexdeck` entrypoint and `--print-config`.
- `agent-cockpit.py`: current TUI implementation, kept under the historical name.
- `codexdeck_core.py`: config loading, TODO parser, command helper, state primitives.
- `codexdeck_runner.py`: process lifecycle, run metrics, log buffer, persistent log writes.
- `codexdeck_ui.py`: pure terminal frame rendering and compact mode.
- `AI_TODO.md`: project backlog and implementation checklist.
- `tests/stubs/codex_stub.py`: local Codex substitute for smoke tests.

Runtime flow:

```text
AI_TODO.md + codexdeck.conf/env
        |
        v
python3 -m codexdeck
        |
        v
agent-cockpit.py
        |
        +-- codexdeck_core.py    parse config and TODO tasks
        +-- codexdeck_runner.py  start/stop one child process and write logs
        +-- codexdeck_ui.py      render the terminal frame
```

Process states used by the runner:

```text
IDLE -> STARTING -> RUNNING -> STOPPING -> IDLE
                         \                 /
                          ------ ERROR ----
```

## Tests

Install dependencies first:

```bash
python3 -m pip install -r requirements.txt
```

Useful commands from the repo root:

```bash
python3 -m pytest tests/unit -q
python3 -m pytest tests/integration -q
python3 -m pytest tests/smoke -q
python3 -m pytest -q
```

PowerShell scripts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

The tests do not require the real `codex` binary. They use fake process handles,
temporary directories, isolated environment variables, and
`tests/stubs/codex_stub.py`.

Manual stub smoke:

```bash
CODEX_CMD="python3 tests/stubs/codex_stub.py --mode success {todo}" python3 -m codexdeck
```

Then press `r`, wait for completion, and press `q`.

## Known Limitations

- No AI_TODO execution flow beyond selecting the first unchecked task and passing the file to Codex.
- No automatic task completion, TODO file editing, checkpointing, or run summary.
- No multi-agent or parallel run support.
- No log search, replay, or rotation.
- No visual diff when `AI_TODO.md` changes.
- No `NO_COLOR` / `FORCE_COLOR` support yet.
- Ellipsis/truncation is simple string-length truncation; wide characters are not fully handled.
- Cross-platform keyboard handling exists, but OS-specific terminal behavior still needs broader validation.
- Packaging is minimal: run from the repo with Python, `requirements.txt`, and the provided scripts.

## Troubleshooting

- `codex` not found: install the Codex CLI or set `CODEX_CMD` to a valid command.
- Invalid command: run `python3 -m codexdeck --print-config` and inspect `CODEX_CMD`.
- No run starts: ensure `AI_TODO.md` exists and has at least one `- [ ] ...` task.
- Missing logs: check `CODEX_LOG_PATH` or write access to `logs/`; the runner creates the directory automatically.
- Small terminal: enlarge the terminal; below 80x20 CodexDeck switches to compact mode.
- Broken borders: run with `CODEX_ASCII_BORDERS=1`.
- Config error: check that every active `codexdeck.conf` line uses `KEY=VALUE`.
