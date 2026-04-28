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
from typing import Optional

from codexdeck_core import CockpitConfig, ConfigError, TodoTask, parse_todo_file
from codexdeck_runner import CodexProcessRunner, ProcessAlreadyRunning, ProcessNotRunning, RunnerState


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
            return ch.decode(errors="ignore")

    def close(self) -> None:
        if not self._is_windows:
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._orig)


class Cockpit:
    def __init__(
        self,
        config: CockpitConfig,
    ) -> None:
        self.config = config
        self.todo_path = config.todo_path
        self.refresh_delay = 1.0 / max(1.0, config.refresh_hz)
        self.tasks: list[TodoTask] = []
        self._todo_mtime = None
        self.last_run = "never"
        self.model = config.model
        self.runner = CodexProcessRunner(
            config.codex_cmd,
            config.log_path,
            max_log_lines=config.max_log_lines,
            stop_timeout=config.stop_timeout,
            run_timeout=config.run_timeout,
        )

    def load_todo_if_changed(self) -> None:
        try:
            stat = self.todo_path.stat()
        except FileNotFoundError:
            self.tasks = []
            return
        if self._todo_mtime == stat.st_mtime:
            return
        self._todo_mtime = stat.st_mtime
        try:
            self.tasks = parse_todo_file(self.todo_path)
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
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width <= 3:
            return text[: max(width, 0)]
        return text[: width - 3] + "..."

    def _render(self, width: int, height: int) -> str:
        left_width = max(24, width // 3)
        right_width = max(20, width - left_width - 3)
        body_h = max(4, height - 4)
        lines = []

        # Top borders and titles
        top_left = "┌" + "─" * left_width + "┬" + "─" * right_width + "┐"
        title_left = f"{'AI_TODO.md':^{left_width}}"
        title_right = f"{'Codex Output':^{right_width}}"
        title_line = "│" + title_left + "│" + title_right + "│"
        lines.append(top_left)
        lines.append(title_line)

        task_texts = []
        for t in self.tasks:
            prefix = "[x] " if t.done else "[ ] "
            task_texts.append(self._truncate(prefix + t.text, left_width - 2))

        right_lines = []
        for line in self.runner.logs()[-body_h:]:
            right_lines.append(self._truncate(line, right_width - 2))
        while len(right_lines) < body_h:
            right_lines.insert(0, "")
        while len(task_texts) < body_h:
            task_texts.append("")

        for i in range(body_h):
            left = task_texts[i].ljust(left_width) if task_texts else "".ljust(left_width)
            right = right_lines[i].ljust(right_width) if right_lines else "".ljust(right_width)
            lines.append("│" + left + "│" + right + "│")

        divider = "├" + "─" * left_width + "┴" + "─" * right_width + "┤"
        lines.append(divider)
        runner_status = self.runner.status()
        status = (
            f"Status: {runner_status.state.value:<8} | Model: {self.model:<7} | "
            f"Last run: {self.last_run:<5} | Errors: {runner_status.errors:<3}"
        )
        lines.append("│" + self._truncate(status, width - 2).ljust(width - 2) + "│")
        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines)

    def stop(self) -> None:
        try:
            self.runner.stop()
        except ProcessNotRunning:
            return

    def loop(self) -> None:
        key_reader = KeyReader()
        self.load_todo_if_changed()
        self.runner.log_buffer.append("> Ready. Press 'r' to run Codex, 's' to stop, 'q' to quit.")

        try:
            while True:
                self.load_todo_if_changed()
                runner_status = self.runner.status()
                key = key_reader.get_key()
                if key:
                    k = key.lower()
                    if k == "q":
                        break
                    if k == "r" and runner_status.state not in {RunnerState.RUNNING, RunnerState.STARTING}:
                        self._start_codex()
                    if k == "s" and runner_status.state == RunnerState.RUNNING:
                        self.stop()
                width, height = shutil.get_terminal_size(fallback=(100, 24))
                content = self._render(width, height)
                print("\033[2J\033[H", end="")
                print(content, end="", flush=True)
                time.sleep(self.refresh_delay)
        finally:
            self.stop()
            key_reader.close()


def main() -> None:
    config = CockpitConfig.from_env(base_dir=Path.cwd())
    cockpit = Cockpit(config=config)
    cockpit.loop()


if __name__ == "__main__":
    main()
