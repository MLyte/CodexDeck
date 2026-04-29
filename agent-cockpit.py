#!/usr/bin/env python3
"""CodexDeck (TUI)

Pilotage terminal simple d'un process Codex basé sur AI_TODO.md.
MVP:
 - Lecture/parsing de la TODO
-  - Liste des tâches dans le volet gauche
- Lancement manuel du process (touche `r`)
- Logs live dans le volet droit
- Barre d'état (IDLE/RUNNING/ERROR)
Non bloquant: UI refresh + lecture clavier async + logs en thread séparé.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Protocol

from codexdeck_core import CockpitConfig, ConfigError, TodoTask, parse_todo_file
from codexdeck_runner import CodexProcessRunner, ProcessAlreadyRunning, ProcessNotRunning, RunnerState
from codexdeck_ui import RenderStatus, clamp_task_offset, render_frame, truncate


class KeyReader:
    """Clavier non bloquant cross-plateforme."""

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
            self._tty.setraw(self._fd)

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
    def __init__(self) -> None:
        self._previous_lines = 0
        self._cleared_once = False

    def __call__(self, content: str) -> None:
        if os.name == "nt":
            if not self._cleared_once:
                os.system("cls")
                self._cleared_once = True
            elif not self._move_windows_cursor_home():
                os.system("cls")
        else:
            print("\033[H" if self._cleared_once else "\033[2J\033[H", end="")
            self._cleared_once = True

        line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
        extra_lines = max(0, self._previous_lines - line_count)
        if extra_lines:
            columns = shutil.get_terminal_size(fallback=(100, 24)).columns
            blank_lines = "\n".join(" " * columns for _ in range(extra_lines))
            content = content + ("\n" if not content.endswith("\n") else "") + blank_lines
        print(content, end="", flush=True)
        self._previous_lines = max(self._previous_lines, line_count)

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
            status = self.runner.start(self.todo_path)
            self.last_run = time.strftime("%H:%M:%S")
            self.runner.log_buffer.append(f"> Running Codex run_id={status.run_id}")
        except ProcessAlreadyRunning:
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
            logs=self.runner.logs(),
            status=RenderStatus(
                state=runner_status.state.value,
                model=self.model,
                last_run=self.last_run,
                errors=runner_status.errors,
                uptime_seconds=getattr(runner_status, "uptime_seconds", None),
                duration_seconds=getattr(runner_status, "duration_seconds", None),
            ),
            width=width,
            height=height,
            ascii_borders=os.getenv("CODEX_ASCII_BORDERS") == "1",
            show_help=self.show_help,
            task_offset=self.task_offset,
        )

    def _visible_task_count(self) -> int:
        _width, height = self._terminal_size()
        if height < 20:
            return 0
        return max(2, height - 5)

    def _scroll_tasks(self, delta: int) -> None:
        visible = self._visible_task_count()
        self.task_offset = clamp_task_offset(len(self.tasks), visible, self.task_offset + delta)

    def stop(self) -> None:
        try:
            self.runner.stop()
        except ProcessNotRunning:
            return

    def loop(self) -> None:
        key_reader = self._key_reader_factory()
        self.load_todo_if_changed()
        self.runner.log_buffer.append("> Ready. Press 'r' run, 's' stop, 'l' reload, 'h/?' help, 'q' quit.")

        try:
            while True:
                self.load_todo_if_changed()
                runner_status = self.runner.status()
                key = key_reader.get_key()
                if key:
                    k = key.lower()
                    if k == "q":
                        break
                    elif k == "r" and runner_status.state not in {RunnerState.RUNNING, RunnerState.STARTING}:
                        self._start_codex()
                    elif k == "s" and runner_status.state == RunnerState.RUNNING:
                        self.stop()
                    elif k == "l":
                        self.load_todo_if_changed(force=True)
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
                content = self._render(width, height)
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
