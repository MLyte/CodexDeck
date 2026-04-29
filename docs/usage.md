# Usage Guide

CodexDeck is launched from the folder you want Codex to work in:

```bash
codexdeck
```

By default it reads `AI_TODO.md` from that folder, writes process logs to `logs/agent.log`, and writes user-facing events to `logs/user.log`.

## Task Plan

CodexDeck parses Markdown task lines:

```text
- [ ] First open task
- [x] Completed task
```

The first unchecked task is treated as the current target. CodexDeck does not mark tasks done by itself; the Codex process must update `AI_TODO.md`.

## Controls

| Key | Action |
| --- | --- |
| `r` | Start a Codex run |
| `s` | Stop the active run |
| `q` | Ask for quit confirmation |
| `e` | Open `AI_TODO.md` in the configured editor |
| `l` | Reload `AI_TODO.md` |
| `n` | Type a new single-line task |
| `m` | Cycle configured model labels |
| `f` | Toggle fast mode |
| `p` | Cycle configured permission labels |
| `o` | Toggle automatic mode |
| `h` or `?` | Toggle help |
| Arrow keys | Scroll tasks |
| Page Up / Page Down | Scroll one visible page |

## Automatic Mode

Automatic mode is conservative. CodexDeck starts another run only after the current process exits successfully and the first open task changes. If Codex exits without moving the plan forward, automatic mode pauses instead of looping forever.

## Logs

CodexDeck keeps a bounded live log in memory and writes persistent logs locally. Sensitive-looking fragments such as tokens, passwords, and API keys are masked before display or persistence.

## Current Limits

- One Codex process at a time.
- Single-line task input from `n`; use `e` for larger edits.
- No visual diff when `AI_TODO.md` changes.
- Cross-platform terminal behavior is tested continuously, but some terminals may handle special keys differently.

