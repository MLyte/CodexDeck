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
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Protocol, TextIO

from codexdeck_core import CockpitConfig, ConfigError, TodoTask, parse_todo_file
from codexdeck_runner import CodexProcessRunner, ProcessAlreadyRunning, ProcessNotRunning, RunStatus, RunnerState
from codexdeck_ui import RenderStatus, clamp_task_offset, format_duration, render_frame, truncate


TODO_SKELETON = """# AI_TODO

## First pass

Replace this example with your first real task:

    - [ ] Describe the first concrete action for Codex.
"""


class KeyReader:
    """Cross-platform non-blocking keyboard reader."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"
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

    def get_key(self) -> Optional[str]:
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
            ch = os.read(self._fd, 3)
            if not ch:
                return None
            decoded = ch.decode(errors="ignore")
            return {
                "\x1b[A": "UP",
                "\x1b[B": "DOWN",
                "\x1b[5": "PGUP",
                "\x1b[6": "PGDN",
            }.get(decoded, decoded)

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
            self._stream.write("\033[2J\033[H" if not self._cleared_once else "\033[H\033[J")
            self._cleared_once = True

        self._stream.write(content)
        self._stream.flush()
        self._last_size = current_size

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
    ) -> None:
        self.config = config
        self.todo_path = config.todo_path
        self.refresh_delay = 1.0 / max(1.0, config.refresh_hz)
        self.tasks: list[TodoTask] = []
        self._todo_mtime = None
        self.last_run = "never"
        self.model = config.model
        self.show_help = False
        self.task_offset = 0
        self.active_task_id: str | None = None
        self.active_task_label = ""
        self.last_task_label = ""
        self.agent_label = self._agent_label(config.codex_cmd)
        self._key_reader_factory = key_reader_factory
        self._terminal_size = terminal_size or self._default_terminal_size
        self._sleeper = sleeper
        self._screen_writer = screen_writer or DefaultScreenWriter()
        self.runner = runner or CodexProcessRunner(
            config.codex_cmd,
            config.log_path,
            max_log_lines=config.max_log_lines,
            stop_timeout=config.stop_timeout,
            run_timeout=config.run_timeout,
        )

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
                self.runner.log_buffer.append("> AI_TODO.md not found. Press n to create a starter file.")
                return
            if task is None:
                self.runner.log_buffer.append("> No open task. Add a '- [ ] ...' line, then press l.")
                return
            self.active_task_id = task.id if task is not None else None
            self.active_task_label = self._task_label(task)
            status = self.runner.start(self.todo_path)
            self.last_run = time.strftime("%H:%M:%S")
            self.runner.log_buffer.append(f"> Target task: {self.active_task_label}")
            self.runner.log_buffer.append(f"> Run started. {self.agent_label} is processing AI_TODO.md.")
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
        return render_frame(
            tasks=self.tasks,
            logs=self._display_logs(self.runner.logs()),
            status=RenderStatus(
                state=runner_status.state.value,
                model=self.model,
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

        if running:
            return f"[{self._activity_spinner()}] {self.agent_label} is running on {self.active_task_label}."
        if not self.todo_path.exists():
            return "AI_TODO.md not found. Press n to create a starter file."
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
        return getattr(status, "running", status.state in {RunnerState.STARTING, RunnerState.RUNNING})

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
    def _agent_label(command: str) -> str:
        return "Stub Codex (simulation)" if "codex_stub.py" in command else "Codex"

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
                "n create a starter file",
                "then edit the first task",
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

    def _create_todo_skeleton(self) -> None:
        if self.todo_path.exists():
            self.runner.log_buffer.append("> AI_TODO.md already exists. Add a '- [ ] ...' line, then press l.")
            return
        try:
            self.todo_path.parent.mkdir(parents=True, exist_ok=True)
            self.todo_path.write_text(TODO_SKELETON, encoding="utf-8")
        except OSError as exc:
            self.runner.log_buffer.append(f"[ERROR] cannot create AI_TODO.md: {exc}")
            return
        self.load_todo_if_changed()
        self.runner.log_buffer.append("> Starter AI_TODO.md created. Replace the first task with your goal.")

    def _summary_lines(self, status: RunStatus) -> list[str]:
        task = self._next_open_task()
        target = self.active_task_label or self.last_task_label or self._task_label(task)
        done_count = sum(1 for task_item in self.tasks if task_item.done)
        total_count = len(self.tasks)
        pending_count = max(0, total_count - done_count)
        duration = format_duration(getattr(status, "duration_seconds", None))

        return [
            f"Target: {target}",
            f"Tasks: {done_count} done | {pending_count} open | {total_count} total",
            f"Last run: {self.last_run} | Duration: {duration} | Errors: {getattr(status, 'errors', 0)}",
        ]

    def stop(self) -> None:
        try:
            self.runner.stop()
        except ProcessNotRunning:
            return

    def loop(self) -> None:
        key_reader = self._key_reader_factory()
        self.load_todo_if_changed()
        self.runner.log_buffer.append("> Ready. Press 'r' run, 's' stop, 'l' reload, 'n' new TODO, 'h/?' help, 'q' quit.")
        if self.agent_label != "Codex":
            self.runner.log_buffer.append(f"> Active mode: {self.agent_label}. No real Codex call will run.")

        try:
            while True:
                self.load_todo_if_changed()
                runner_status = self.runner.status()
                key = key_reader.get_key()
                if key:
                    k = key.lower()
                    if k == "q":
                        break
                    elif k == "r" and not self._status_running(runner_status):
                        self._start_codex()
                    elif k == "s" and self._status_running(runner_status):
                        self.stop()
                    elif k == "s":
                        self.runner.log_buffer.append("> No active run to stop.")
                    elif k == "l":
                        self.load_todo_if_changed(force=True)
                    elif k == "n":
                        self._create_todo_skeleton()
                    elif k in {"h", "?"}:
                        self.show_help = not self.show_help
                    elif k in {"j", "down"}:
                        self._scroll_tasks(1)
                    elif k in {"k", "up"}:
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
                    self.active_task_id = None
                    self.active_task_label = ""
                self._screen_writer(content)
                self._sleeper(self.refresh_delay)
        finally:
            self.stop()
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
