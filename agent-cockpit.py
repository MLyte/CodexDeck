#!/usr/bin/env python3
"""CodexDeck (TUI)

Small terminal cockpit for driving one Codex process from AI_TODO.md.
MVP:
- read and parse the TODO file
- show the task list in the left pane
- start the process manually with `r`
- show live logs in the right pane
- show a status bar (IDLE/RUNNING/ERROR)
Non-blocking: UI refresh, async keyboard polling, and threaded log reading.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from shlex import split as shlex_split
from typing import Callable, Optional, Protocol, TextIO

from codexdeck_core import CockpitConfig, ConfigError, TodoTask, parse_todo_file
from codexdeck_runner import CodexProcessRunner, ProcessAlreadyRunning, ProcessNotRunning, RunStatus, RunnerState
from codexdeck_ui import RenderStatus, clamp_task_offset, format_duration, render_frame, truncate


class KeyReader:
    """Cross-platform non-blocking keyboard reader."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"
        self._pending_keys: list[str] = []
        self._pending_posix = ""
        if self._is_windows:
            import msvcrt

            self._msvcrt = msvcrt
        else:
            import sys
            import tty
            import termios

            self._tty = tty
            self._termios = termios
            self._fd = sys.stdin.fileno()
            self._orig = self._termios.tcgetattr(self._fd)
            self._tty.setcbreak(self._fd)
            attrs = self._termios.tcgetattr(self._fd)
            attrs[0] &= ~self._termios.IXON
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, attrs)

    def get_key(self) -> Optional[str]:
        if self._pending_keys:
            return self._pending_keys.pop(0)
        if self._is_windows:
            if not self._msvcrt.kbhit():
                return None
            key = self._msvcrt.getch()
            if key in {b"\x00", b"\xe0"}:
                code = self._msvcrt.getch()
                return {
                    b"H": "UP",
                    b"P": "DOWN",
                    b"I": "PGUP",
                    b"Q": "PGDN",
                }.get(code)
            try:
                return key.decode("utf-8")
            except UnicodeDecodeError:
                return None
        else:
            import select

            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if not rlist:
                return None
            ch = os.read(self._fd, 8)
            if not ch:
                return None
            keys, remainder = self._decode_posix_keys(self._pending_posix + ch.decode(errors="ignore"))
            self._pending_posix = remainder
            self._pending_keys.extend(keys)
            if self._pending_keys:
                return self._pending_keys.pop(0)
            return None

    @staticmethod
    def _decode_posix_key(decoded: str) -> str:
        keys, remainder = KeyReader._decode_posix_keys(decoded)
        if keys:
            return keys[0]
        return remainder or decoded

    @staticmethod
    def _decode_posix_keys(decoded: str) -> tuple[list[str], str]:
        keys: list[str] = []
        index = 0
        while index < len(decoded):
            if decoded.startswith("\x1b[A", index):
                keys.append("UP")
                index += 3
            elif decoded.startswith("\x1b[B", index):
                keys.append("DOWN")
                index += 3
            elif decoded.startswith("\x1b[5~", index):
                keys.append("PGUP")
                index += 4
            elif decoded.startswith("\x1b[6~", index):
                keys.append("PGDN")
                index += 4
            elif decoded.startswith("\x1b[5", index) and index + 3 == len(decoded):
                keys.append("PGUP")
                index += 3
            elif decoded.startswith("\x1b[6", index) and index + 3 == len(decoded):
                keys.append("PGDN")
                index += 3
            elif decoded[index] == "\x1b":
                if index == len(decoded) - 1 or decoded.startswith("\x1b[", index):
                    return keys, decoded[index:]
                index += 1
            else:
                keys.append(decoded[index])
                index += 1
        return keys, ""

    def close(self) -> None:
        if not self._is_windows:
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._orig)


class KeyReaderLike(Protocol):
    def get_key(self) -> Optional[str]:
        ...

    def close(self) -> None:
        ...


class DefaultScreenWriter:
    def __init__(
        self,
        *,
        terminal_size: Callable[[], tuple[int, int]] | None = None,
        stream: TextIO | None = None,
        is_windows: bool | None = None,
    ) -> None:
        self._cleared_once = False
        self._entered_alternate_screen = False
        self._last_size: tuple[int, int] | None = None
        self._terminal_size = terminal_size or self._default_terminal_size
        self._stream = stream or sys.stdout
        self._is_windows = os.name == "nt" if is_windows is None else is_windows

    def __call__(self, content: str) -> None:
        current_size = self._terminal_size()
        size_changed = self._last_size is not None and current_size != self._last_size

        if self._is_windows:
            if not self._cleared_once:
                os.system("cls")
                self._cleared_once = True
            elif size_changed or not self._move_windows_cursor_home():
                os.system("cls")
        else:
            if not self._entered_alternate_screen:
                self._stream.write("\033[?1049h")
                self._entered_alternate_screen = True
            self._stream.write("\033[2J\033[H" if not self._cleared_once else "\033[H\033[J")
            self._cleared_once = True

        self._stream.write(content)
        self._stream.flush()
        self._last_size = current_size

    def close(self) -> None:
        if not self._is_windows and self._entered_alternate_screen:
            self._stream.write("\033[?1049l")
            self._stream.flush()
            self._entered_alternate_screen = False

    @staticmethod
    def _default_terminal_size() -> tuple[int, int]:
        size = shutil.get_terminal_size(fallback=(100, 24))
        return size.columns, size.lines

    @staticmethod
    def _move_windows_cursor_home() -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            stdout = ctypes.windll.kernel32.GetStdHandle(-11)
            coord = wintypes._COORD(0, 0)
            return bool(ctypes.windll.kernel32.SetConsoleCursorPosition(stdout, coord))
        except Exception:
            return False


class Cockpit:
    def __init__(
        self,
        config: CockpitConfig,
        *,
        key_reader_factory: Callable[[], KeyReaderLike] = KeyReader,
        terminal_size: Callable[[], tuple[int, int]] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        screen_writer: Callable[[str], None] | None = None,
        runner: CodexProcessRunner | None = None,
        editor_runner: Callable[[Path], int] | None = None,
    ) -> None:
        self.config = config
        self.todo_path = config.todo_path
        self.user_log_path = config.user_log_path
        self.refresh_delay = 1.0 / max(1.0, config.refresh_hz)
        self.tasks: list[TodoTask] = []
        self._todo_mtime = None
        self.last_run = "never"
        self.models = self._choices_with_current(config.models, config.model)
        self.model = config.model
        self.fast_model = config.fast_model
        self.fast_mode = False
        self.permissions = self._choices_with_current(config.permissions, config.permission)
        self.permission = config.permission
        self.quit_confirmation = False
        self.task_input_active = False
        self.task_input_buffer = ""
        self.auto_mode = False
        self._last_auto_task_id = ""
        self.show_help = False
        self.task_offset = 0
        self.active_task_id: str | None = None
        self.active_task_label = ""
        self.last_task_label = ""
        self._logged_terminal_run_ids: set[str] = set()
        self._stop_thread: threading.Thread | None = None
        self.agent_label = self._agent_label(config.codex_cmd)
        self._key_reader_factory = key_reader_factory
        self._terminal_size = terminal_size or self._default_terminal_size
        self._sleeper = sleeper
        self._screen_writer = screen_writer or DefaultScreenWriter()
        self._editor_runner = editor_runner or self._run_terminal_editor
        self.runner = runner or CodexProcessRunner(
            config.codex_cmd,
            config.log_path,
            max_log_lines=config.max_log_lines,
            stop_timeout=config.stop_timeout,
            run_timeout=config.run_timeout,
        )

    @staticmethod
    def _choices_with_current(choices: tuple[str, ...], current: str) -> tuple[str, ...]:
        values = [current.strip()] if current.strip() else []
        for choice in choices:
            cleaned = choice.strip()
            if cleaned and cleaned not in values:
                values.append(cleaned)
        return tuple(values)

    @staticmethod
    def _default_terminal_size() -> tuple[int, int]:
        size = shutil.get_terminal_size(fallback=(100, 24))
        return size.columns, size.lines

    def load_todo_if_changed(self, *, force: bool = False) -> None:
        try:
            stat = self.todo_path.stat()
        except FileNotFoundError:
            self.tasks = []
            self._todo_mtime = None
            return
        if not force and self._todo_mtime == stat.st_mtime:
            return
        self._todo_mtime = stat.st_mtime
        try:
            self.tasks = parse_todo_file(self.todo_path)
            self.task_offset = clamp_task_offset(len(self.tasks), self._visible_task_count(), self.task_offset)
            if force:
                self.runner.log_buffer.append("> Reloaded AI_TODO.md")
        except ConfigError as exc:
            self.tasks = []
            self.runner.log_buffer.append(f"[ERROR] {exc.message}")

    def _start_codex(self) -> None:
        try:
            task = self._next_open_task()
            if not self.todo_path.exists():
                self.runner.log_buffer.append("> AI_TODO.md not found. Press n to add the first task.")
                return
            if task is None:
                self.runner.log_buffer.append("> No open task. Add a '- [ ] ...' line, then press l.")
                return
            self.active_task_id = task.id if task is not None else None
            self.active_task_label = self._task_label(task)
            self._apply_effective_command()
            status = self.runner.start(self.todo_path)
            self.last_run = time.strftime("%H:%M:%S")
            self.runner.log_buffer.append(f"> Target task: {self.active_task_label}")
            self.runner.log_buffer.append(
                f"> Run started. {self.agent_label} is processing AI_TODO.md "
                f"with model {self._effective_model()} and permission {self.permission}."
            )
            self._record_user_event(
                f"run started | target={self.active_task_label} | model={self._effective_model()} | "
                f"fast={self.fast_mode} | permission={self.permission} | run_id={getattr(status, 'run_id', '-')}"
            )
        except ProcessAlreadyRunning:
            self.runner.log_buffer.append("> A run is already active.")
            return
        except Exception as exc:
            self.runner.log_buffer.append(f"[ERROR] cannot start Codex: {exc}")

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        return truncate(text, width)

    def _render(self, width: int, height: int) -> str:
        runner_status = self.runner.status()
        logs = self._help_lines() if self.show_help else self._display_logs(self.runner.logs())
        return render_frame(
            tasks=self.tasks,
            logs=logs,
            status=RenderStatus(
                state=runner_status.state.value,
                model=self._effective_model(),
                permission=self.permission,
                fast_mode=self.fast_mode,
                auto_mode=self.auto_mode,
                last_run=self.last_run,
                errors=runner_status.errors,
                uptime_seconds=getattr(runner_status, "uptime_seconds", None),
                duration_seconds=getattr(runner_status, "duration_seconds", None),
                message=self._activity_message(runner_status),
            ),
            width=width,
            height=height,
            ascii_borders=os.getenv("CODEX_ASCII_BORDERS") == "1",
            show_help=self.show_help,
            task_offset=self.task_offset,
            active_task_id=self.active_task_id,
            task_panel_hint=self._task_panel_hint(),
            summary_lines=self._summary_lines(runner_status),
        )

    def _activity_message(self, status: RunStatus) -> str:
        running = self._status_running(status)
        returncode = getattr(status, "returncode", None)
        last_error = getattr(status, "last_error", None)
        metrics = getattr(status, "metrics", None)
        runs_total = getattr(metrics, "runs_total", 0)

        if status.state == RunnerState.STOPPING:
            return f"Stopping {self.agent_label} on {self.active_task_label or self.last_task_label}."
        if running:
            return f"[{self._activity_spinner()}] {self.agent_label} is running on {self.active_task_label}."
        if self.quit_confirmation:
            return "Quit CodexDeck? Press y to confirm, n or Esc to cancel."
        if self.task_input_active:
            text = self.task_input_buffer or " "
            return f"New task: {text} | Ctrl-S save, Esc cancel, Backspace edit."
        if self.auto_mode:
            return "Auto mode on. Successful runs continue with the next checked-off task."
        if not self.todo_path.exists():
            return "AI_TODO.md not found. Press n to add the first task."
        if self._next_open_task() is None:
            if self.tasks:
                return "All tasks are checked. Add an open task, then press l."
            return "AI_TODO.md has no tasks. Add '- [ ] ...', then press l."
        if status.state == RunnerState.ERROR:
            if returncode is not None:
                return f"Error code {returncode} on {self.last_task_label or self.active_task_label}."
            if last_error:
                return f"Error: {last_error}"
            return "Last run failed."
        if runs_total == 0:
            return f"Ready. Press r to start {self.agent_label}."
        if returncode == 0:
            return f"OK on {self.last_task_label or self.active_task_label}."
        if returncode is not None:
            return f"Last run exited with code {returncode}."
        return f"Ready. Press r to restart {self.agent_label}."

    @staticmethod
    def _status_running(status: RunStatus) -> bool:
        return getattr(status, "running", status.state in {RunnerState.STARTING, RunnerState.RUNNING, RunnerState.STOPPING})

    @staticmethod
    def _activity_spinner() -> str:
        frames = ("|", "/", "-", "\\")
        return frames[int(time.monotonic() * 8) % len(frames)]

    def _display_logs(self, logs: list[str]) -> list[str]:
        visible: list[str] = []
        for line in logs:
            codex_output = re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+\[[0-9a-f]{32}\]\s+", line) is not None
            text = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+", "", line)
            text = re.sub(r"\[[0-9a-f]{32}\]\s*", "", text)
            text = re.sub(r"\[(INFO|WARN|ERROR)\]\s+run\s+[0-9a-f]{32}\s+", "", text)
            text = re.sub(r"started pid=\d+", "Run started.", text)
            text = text.replace("finished rc=0", "Run completed successfully.")
            text = re.sub(r"finished rc=(-?\d+)", r"Run exited with code \1.", text)
            if re.match(r"codex_stub mode=\w+\s+todo=.*", text):
                text = "Simulation started."
            if codex_output:
                text = f"{self.agent_label} output: {text}"
            visible.append(text)
        return visible

    @staticmethod
    def _help_lines() -> list[str]:
        return [
            "Help: CodexDeck keeps AI_TODO.md visible, runs one Codex process, and streams output.",
            "(r)un first open task | (s)top active run | (q)uit with confirmation.",
            "(e)dit opens AI_TODO.md in nano | (n)ew: Ctrl-S saves, Esc cancels | re(l)oad.",
            "(M)odel, (F)ast, (Pe)rm, Aut(o) adjust next run options | \u2191\u2193 scroll tasks.",
            "made by lyte | GitHub: https://github.com/MLyte/CodexDeck",
        ]

    @staticmethod
    def _agent_label(command: str) -> str:
        return "Stub Codex (simulation)" if "codex_stub.py" in command else "Codex"

    def _effective_model(self) -> str:
        if self.fast_mode and self.fast_model:
            return self.fast_model
        return self.model

    def _apply_effective_command(self) -> None:
        command = self.config.codex_cmd
        if any(placeholder in command for placeholder in ("{model}", "{permission}", "{fast}")):
            command = (
                command.replace("{model}", self._effective_model())
                .replace("{permission}", self.permission)
                .replace("{fast}", "1" if self.fast_mode else "0")
            )
        self.runner.command = command

    def _next_open_task(self) -> TodoTask | None:
        return next((task for task in self.tasks if not task.done), None)

    @staticmethod
    def _task_label(task: TodoTask | None) -> str:
        if task is None:
            return "No open task"
        return f"line {task.line}: {task.text}"

    @staticmethod
    def _visible_task_count_for_height(height: int) -> int:
        if height < 20:
            return 0
        available_h = max(6, height - 9)
        return max(3, min(8, available_h // 3 + 1))

    def _visible_task_count(self) -> int:
        _width, height = self._terminal_size()
        return self._visible_task_count_for_height(height)

    def _scroll_tasks(self, delta: int) -> None:
        visible = self._visible_task_count()
        self.task_offset = clamp_task_offset(len(self.tasks), visible, self.task_offset + delta)

    def _task_panel_hint(self) -> list[str]:
        if self.tasks:
            return []
        if not self.todo_path.exists():
            return [
                "No AI_TODO.md",
                "",
                "n add the first task",
                "Ctrl-S saves it",
                "",
                "r will start Codex after that",
            ]
        return [
            "No open task",
            "",
            "Add a line:",
            "- [ ] First action",
            "",
            "l reload, r run",
        ]

    def _begin_task_input(self) -> None:
        self.task_input_active = True
        self.task_input_buffer = ""
        self.quit_confirmation = False
        self.runner.log_buffer.append("> New task input. Type the task, then press Ctrl-S to save or Esc to cancel.")

    def _handle_task_input_key(self, key: str) -> None:
        if key in {"\x1b", "ESC"}:
            self.task_input_active = False
            self.task_input_buffer = ""
            self.runner.log_buffer.append("> New task cancelled.")
            self._record_user_event("task input cancelled")
            return
        if key == "\x13":
            self._save_task_input()
            return
        if key in {"\x7f", "\b"}:
            self.task_input_buffer = self.task_input_buffer[:-1]
            return
        if key in {"\r", "\n", "\t"}:
            return
        if len(key) == 1 and key.isprintable():
            self.task_input_buffer += key

    def _save_task_input(self) -> None:
        text = " ".join(self.task_input_buffer.split())
        if not text:
            self.runner.log_buffer.append("> New task is empty. Type a task or press Esc to cancel.")
            return
        try:
            self.todo_path.parent.mkdir(parents=True, exist_ok=True)
            prefix = ""
            if self.todo_path.exists() and self.todo_path.stat().st_size > 0:
                current = self.todo_path.read_text(encoding="utf-8", errors="replace")
                prefix = "" if current.endswith("\n") else "\n"
            elif not self.todo_path.exists():
                self.todo_path.write_text("# AI_TODO\n\n", encoding="utf-8")
            with self.todo_path.open("a", encoding="utf-8") as todo_file:
                todo_file.write(f"{prefix}- [ ] {text}\n")
        except OSError as exc:
            self.runner.log_buffer.append(f"[ERROR] cannot save task to AI_TODO.md: {exc}")
            return
        self.task_input_active = False
        self.task_input_buffer = ""
        self.load_todo_if_changed(force=True)
        self.runner.log_buffer.append("> New task saved to AI_TODO.md.")
        self._record_user_event(f"task added | text={text}")

    @staticmethod
    def _run_terminal_editor(todo_path: Path) -> int:
        editor = os.getenv("CODEXDECK_EDITOR") or os.getenv("VISUAL") or os.getenv("EDITOR") or "nano"
        command = [*shlex_split(editor), str(todo_path)]
        return subprocess.run(command, check=False).returncode

    def _open_todo_editor(self, key_reader: KeyReaderLike) -> KeyReaderLike:
        try:
            self.todo_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.todo_path.exists():
                self.todo_path.write_text("# AI_TODO\n\n- [ ] First task\n", encoding="utf-8")
                self.runner.log_buffer.append("> Created AI_TODO.md before opening editor.")
        except OSError as exc:
            self.runner.log_buffer.append(f"[ERROR] cannot prepare AI_TODO.md for editor: {exc}")
            return key_reader

        self.runner.log_buffer.append("> Opening AI_TODO.md in nano. Save or cancel there to return to CodexDeck.")
        self._record_user_event(f"editor opened | path={self.todo_path}")

        close_writer = getattr(self._screen_writer, "close", None)
        if callable(close_writer):
            close_writer()
        key_reader.close()

        try:
            returncode = self._editor_runner(self.todo_path)
        except OSError as exc:
            self.runner.log_buffer.append(f"[ERROR] cannot open nano: {exc}")
            self._record_user_event(f"editor failed | error={exc}")
        else:
            if returncode == 0:
                self.runner.log_buffer.append("> Back from nano. AI_TODO.md reloaded.")
                self._record_user_event(f"editor closed | path={self.todo_path} | returncode=0")
            else:
                self.runner.log_buffer.append(f"> Back from nano. Editor exited with code {returncode}. AI_TODO.md reloaded.")
                self._record_user_event(f"editor closed | path={self.todo_path} | returncode={returncode}")

        self.task_input_active = False
        self.task_input_buffer = ""
        self.quit_confirmation = False
        self.load_todo_if_changed(force=True)
        return self._key_reader_factory()

    def _cycle_model(self) -> None:
        if not self.models:
            self.runner.log_buffer.append("> No models configured.")
            return
        if self.fast_mode:
            self.fast_mode = False
        current_index = self.models.index(self.model) if self.model in self.models else -1
        self.model = self.models[(current_index + 1) % len(self.models)]
        self.runner.log_buffer.append(f"> Model selected for next run: {self.model}.")
        self._record_user_event(f"model selected | model={self.model}")

    def _toggle_fast_mode(self) -> None:
        self.fast_mode = not self.fast_mode
        state = "on" if self.fast_mode else "off"
        self.runner.log_buffer.append(f"> Fast mode {state}. Next run model: {self._effective_model()}.")
        self._record_user_event(f"fast mode {state} | model={self._effective_model()}")

    def _cycle_permission(self) -> None:
        if not self.permissions:
            self.runner.log_buffer.append("> No Codex permissions configured.")
            return
        current_index = self.permissions.index(self.permission) if self.permission in self.permissions else -1
        self.permission = self.permissions[(current_index + 1) % len(self.permissions)]
        self.runner.log_buffer.append(f"> Codex permission for next run: {self.permission}.")
        self._record_user_event(f"permission selected | permission={self.permission}")

    def _record_user_event(self, event: str) -> None:
        stamped = f"{datetime.now().isoformat(timespec='seconds')} {event}"
        self.user_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.user_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(stamped + "\n")

    def _record_terminal_run_if_needed(self, status: RunStatus) -> None:
        run_id = getattr(status, "run_id", None)
        if not run_id or run_id in self._logged_terminal_run_ids or self._status_running(status):
            return
        returncode = getattr(status, "returncode", None)
        duration = format_duration(getattr(status, "duration_seconds", None))
        if getattr(status, "state", None) == RunnerState.ERROR:
            outcome = f"failed | error={getattr(status, 'last_error', None) or returncode}"
        elif returncode == 0:
            outcome = "completed"
        elif returncode is None:
            outcome = "stopped"
        else:
            outcome = f"exited | code={returncode}"
        self._record_user_event(
            f"run {outcome} | target={self.last_task_label or self.active_task_label or '-'} | "
            f"duration={duration} | run_id={run_id}"
        )
        self._logged_terminal_run_ids.add(run_id)

    def _summary_lines(self, status: RunStatus) -> list[str]:
        task = self._next_open_task()
        target = self.active_task_label or self.last_task_label or self._task_label(task)
        done_count = sum(1 for task_item in self.tasks if task_item.done)
        total_count = len(self.tasks)
        pending_count = max(0, total_count - done_count)
        duration = format_duration(getattr(status, "duration_seconds", None))

        return [
            f"Target: {target}",
            f"Tasks: {done_count} done | {pending_count} open | {total_count} total | Auto: {'on' if self.auto_mode else 'off'}",
            f"Last run: {self.last_run} | Duration: {duration} | Errors: {getattr(status, 'errors', 0)}",
        ]

    def _stop_is_active(self) -> bool:
        return self._stop_thread is not None and self._stop_thread.is_alive()

    def stop(self, *, block: bool = True) -> None:
        if self._stop_is_active():
            if block and self._stop_thread is not None:
                self._stop_thread.join()
            return

        def stop_runner() -> None:
            try:
                self.runner.stop()
            except ProcessNotRunning:
                return
            except Exception as exc:
                self.runner.log_buffer.append(f"[ERROR] cannot stop Codex: {exc}")

        try:
            status = self.runner.status()
        except ProcessNotRunning:
            return
        if not self._status_running(status):
            return
        if block:
            stop_runner()
            return
        self.runner.log_buffer.append("> Stop requested.")
        self._stop_thread = threading.Thread(target=stop_runner, name="codexdeck-stop", daemon=True)
        self._stop_thread.start()

    def _toggle_auto_mode(self) -> None:
        self.auto_mode = not self.auto_mode
        if self.auto_mode:
            task = self._next_open_task()
            self._last_auto_task_id = task.id if task is not None else ""
        else:
            self._last_auto_task_id = ""
        state = "on" if self.auto_mode else "off"
        self.runner.log_buffer.append(f"> Auto mode {state}.")
        self._record_user_event(f"auto mode {state}")

    def _maybe_start_next_auto_run(self, status: RunStatus) -> None:
        if not self.auto_mode or self._status_running(status) or getattr(status, "returncode", None) != 0:
            return
        self.load_todo_if_changed(force=True)
        next_task = self._next_open_task()
        if next_task is None:
            self.auto_mode = False
            self._last_auto_task_id = ""
            self.runner.log_buffer.append("> Auto mode off. No open tasks remain.")
            self._record_user_event("auto mode off | reason=no open tasks")
            return
        if next_task.id == self._last_auto_task_id:
            self.auto_mode = False
            self.runner.log_buffer.append("> Auto mode paused. The previous task is still open.")
            self._record_user_event("auto mode paused | reason=previous task still open")
            return
        self._last_auto_task_id = next_task.id
        self.runner.log_buffer.append(f"> Auto mode starting next task: {self._task_label(next_task)}.")
        self._record_user_event(f"auto next task | target={self._task_label(next_task)}")
        self._start_codex()

    def loop(self) -> None:
        key_reader = self._key_reader_factory()
        self.load_todo_if_changed()
        self.runner.log_buffer.append("> Ready. Press h for help.")
        if self.agent_label != "Codex":
            self.runner.log_buffer.append(f"> Active mode: {self.agent_label}. No real Codex call will run.")

        try:
            while True:
                self.load_todo_if_changed()
                runner_status = self.runner.status()
                key = key_reader.get_key()
                if key:
                    if self.task_input_active:
                        self._handle_task_input_key(key)
                    else:
                        k = key.lower()
                        if self.quit_confirmation:
                            if k == "y":
                                break
                            if k in {"n", "\x1b"}:
                                self.quit_confirmation = False
                                self.runner.log_buffer.append("> Quit cancelled.")
                                self._record_user_event("quit cancelled")
                            else:
                                self.runner.log_buffer.append("> Quit pending. Press y to confirm, n or Esc to cancel.")
                        elif k == "q":
                            self.quit_confirmation = True
                            self.runner.log_buffer.append("> Quit CodexDeck? Press y to confirm, n or Esc to cancel.")
                        elif k == "r" and not self._status_running(runner_status):
                            self._start_codex()
                        elif k == "s" and self._status_running(runner_status):
                            self.stop(block=False)
                        elif k == "s":
                            self.runner.log_buffer.append("> No active run to stop.")
                        elif k == "l":
                            self.load_todo_if_changed(force=True)
                            self._record_user_event(f"TODO reloaded | tasks={len(self.tasks)}")
                        elif k == "n":
                            self._begin_task_input()
                        elif k == "e" and not self._status_running(runner_status):
                            key_reader = self._open_todo_editor(key_reader)
                        elif k == "e":
                            self.runner.log_buffer.append("> Stop the active Codex run before editing AI_TODO.md in nano.")
                        elif k == "m":
                            self._cycle_model()
                        elif k == "f":
                            self._toggle_fast_mode()
                        elif k == "p":
                            self._cycle_permission()
                        elif k == "o":
                            self._toggle_auto_mode()
                        elif k in {"h", "?"}:
                            self.show_help = not self.show_help
                        elif k == "down":
                            self._scroll_tasks(1)
                        elif k == "up":
                            self._scroll_tasks(-1)
                        elif k == "pgdn":
                            self._scroll_tasks(self._visible_task_count())
                        elif k == "pgup":
                            self._scroll_tasks(-self._visible_task_count())
                        else:
                            self.runner.log_buffer.append(f"> Ignored key: {repr(key)}")
                width, height = self._terminal_size()
                visible_tasks = self._visible_task_count_for_height(height)
                self.task_offset = clamp_task_offset(len(self.tasks), visible_tasks, self.task_offset)
                content = self._render(width, height)
                refreshed_status = self.runner.status()
                if not self._status_running(refreshed_status) and self.active_task_label:
                    self.last_task_label = self.active_task_label
                    self.active_task_label = ""
                self._record_terminal_run_if_needed(refreshed_status)
                self._maybe_start_next_auto_run(refreshed_status)
                self._screen_writer(content)
                self._sleeper(self.refresh_delay)
        finally:
            self.stop()
            close_writer = getattr(self._screen_writer, "close", None)
            if callable(close_writer):
                close_writer()
            key_reader.close()


def main() -> None:
    try:
        config = CockpitConfig.from_env(base_dir=Path.cwd())
        cockpit = Cockpit(config=config)
        cockpit.loop()
    except ConfigError as exc:
        print(f"Config error [{exc.error_code.value}]: {exc.message}", file=sys.stderr)
        if exc.cause is not None:
            print(f"Cause: {exc.cause}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        print("\nCodexDeck stopped cleanly.")
        raise SystemExit(0)


if __name__ == "__main__":
    main()
