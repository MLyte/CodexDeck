# Configuration Reference

CodexDeck reads `codexdeck.conf` from the launch folder when present, then applies environment variable overrides.

The config file format is one `KEY=VALUE` pair per line. Empty lines and `#` comments are ignored.

## Main Settings

| Key | Default | Purpose |
| --- | --- | --- |
| `CODEX_CMD` | `codex {todo}` | Command used to start Codex |
| `CODEX_MODEL` | `gpt-5.5` | Current model label |
| `CODEX_MODELS` | built in list | Comma-separated labels cycled by `m` |
| `CODEX_FAST_MODEL` | `gpt-5.3-codex-spark` | Model label used when fast mode is on |
| `CODEX_PERMISSION` | `default` | Current permission label |
| `CODEX_PERMISSIONS` | built in list | Comma-separated labels cycled by `p` |
| `RUN_TIMEOUT_SECONDS` | `3600` | Maximum run duration |
| `STOP_TIMEOUT_SECONDS` | `5` | Stop escalation delay |
| `STATE_REFRESH_HZ` | `8` | UI refresh rate |
| `MAX_LOG_LINES` | `5000` | In-memory log limit |
| `CODEX_TODO_PATH` or `TODO_PATH` | `AI_TODO.md` | Task plan path |
| `CODEX_LOG_PATH` or `LOG_PATH` | `logs/agent.log` | Process log path |
| `CODEX_USER_LOG_PATH` or `USER_LOG_PATH` | `logs/user.log` | User event log path |
| `CODEX_CONFIG_PATH` | `codexdeck.conf` | Alternate config file path |
| `CODEXDECK_EDITOR` | `nano` | Terminal editor command for `e` |
| `CODEX_ASCII_BORDERS` | unset | Set to `1` to force ASCII borders |

Relative paths are resolved against the folder where you launch `codexdeck`.

## Command Placeholders

`CODEX_CMD` supports:

- `{todo}`: resolved TODO file path.
- `{model}`: current effective model.
- `{permission}`: current permission label.
- `{fast}`: `1` when fast mode is on, otherwise `0`.

Example:

```text
CODEX_CMD=codex exec --model {model} --sandbox {permission} "Read {todo}. Work on the first unchecked task only."
CODEX_MODELS=gpt-5.5,gpt-5.4,gpt-5.4-mini
CODEX_FAST_MODEL=gpt-5.4-mini
CODEX_PERMISSIONS=read-only,workspace-write
```

Keep the prompt inside `CODEX_CMD` in English if it is sent directly to the model.

