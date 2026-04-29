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

Use `k` to skip the current open task. CodexDeck marks it as checked and appends `# skipped`, so the next open task becomes the target.

## Controls

| Key | Action |
| --- | --- |
| `r` | Start a Codex run |
| `s` | Stop the active run |
| `k` | Skip the current open task |
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

## Codex Questions

When `codex exec` prints a final question, CodexDeck keeps it visible as `Question from Codex`. Because `codex exec` is a batch command, that final question is not always an interactive stdin prompt. Use `e` to edit `AI_TODO.md`, `r` to rerun after clarifying the task, or `k` to skip the step.

## Logs

CodexDeck keeps a bounded live log in memory and writes persistent logs locally. Sensitive-looking fragments such as tokens, passwords, and API keys are masked before display or persistence.

## Current Limits

- One Codex process at a time.
- Single-line task input from `n`; use `e` for larger edits.
- Final questions from `codex exec` are displayed, but may require editing/rerunning rather than direct stdin answers.
- No visual diff when `AI_TODO.md` changes.
- Cross-platform terminal behavior is tested continuously, but some terminals may handle special keys differently.
