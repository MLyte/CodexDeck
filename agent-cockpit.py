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
from codexdeck_ui import RenderStatus, render_frame, truncate


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
            ),
            width=width,
            height=height,
            ascii_borders=os.getenv("CODEX_ASCII_BORDERS") == "1",
        )

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
