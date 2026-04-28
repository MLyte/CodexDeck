#!/usr/bin/env python3
"""Agent Cockpit (TUI)

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
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import List, Optional


STATE = {"IDLE", "RUNNING", "ERROR"}
TODO_RE = re.compile(r"^\s*[-*]?\s*\[(?P<state>[xX\s])\]\s*(?P<text>.+?)\s*$")


@dataclass
class Task:
    text: str
    done: bool


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
        todo_path: Path,
        log_path: Path,
        refresh_hz: float = 8.0,
    ) -> None:
        self.todo_path = todo_path
        self.log_path = log_path
        self.refresh_delay = 1.0 / max(1.0, refresh_hz)
        self.tasks: List[Task] = []
        self._todo_mtime = None
        self.state = "IDLE"
        self.errors = 0
        self.last_run = "never"
        self.model = os.getenv("CODEX_MODEL", "normal")
        self.log_queue: "Queue[str]" = Queue()
        self.lines = deque(maxlen=5000)
        self.proc: Optional[subprocess.Popen[str]] = None
        self.reader: Optional[threading.Thread] = None
        self._running = False
        self._stop_requested = threading.Event()

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = self.log_path.open("a", encoding="utf-8")

    def parse_todo(self) -> List[Task]:
        if not self.todo_path.exists():
            return []
        raw = self.todo_path.read_text(encoding="utf-8", errors="ignore")
        tasks: List[Task] = []
        for line in raw.splitlines():
            match = TODO_RE.match(line)
            if not match:
                continue
            state = match.group("state")
            text = match.group("text").strip()
            tasks.append(Task(text=text, done=state.lower() == "x"))
        return tasks

    def load_todo_if_changed(self) -> None:
        try:
            stat = self.todo_path.stat()
        except FileNotFoundError:
            self.tasks = []
            return
        if self._todo_mtime == stat.st_mtime:
            return
        self._todo_mtime = stat.st_mtime
        self.tasks = self.parse_todo()

    def build_command(self) -> List[str]:
        raw = os.getenv("CODEX_CMD", "codex").strip()
        todo_abs = str(self.todo_path.resolve())
        raw = raw.replace("{todo}", todo_abs).replace("$TODO", todo_abs).replace("%TODO%", todo_abs)
        args = shlex.split(raw, posix=os.name != "nt")
        if not args:
            return ["codex"]
        return args

    def _reader_thread(self, pipe, process: subprocess.Popen[str]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                if self._stop_requested.is_set():
                    break
                text = line.rstrip("\n\r")
                timestamp = datetime.now().strftime("%H:%M:%S")
                payload = f"[{timestamp}] {text}"
                self.log_queue.put(payload)
                self._log_file.write(payload + "\n")
                self._log_file.flush()
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    def _start_codex(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        cmd = self.build_command()
        self.lines.clear()
        self._stop_requested.clear()
        self.state = "RUNNING"
        self.last_run = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"> Running Codex: {' '.join(cmd)}")

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
        except Exception as exc:
            self.state = "ERROR"
            self.errors += 1
            self.lines.append(f"[ERROR] {exc}")
            self.log_queue.put(f"[ERROR] cannot start Codex: {exc}")
            return

        self.reader = threading.Thread(
            target=self._reader_thread,
            args=(self.proc.stdout, self.proc),
            daemon=True,
        )
        self.reader.start()
        self._running = True

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except Empty:
                break
            self.lines.append(line)

    def _flush_queue_to_lines(self) -> None:
        self._drain_logs()

    def _check_process(self) -> None:
        if not self._running or self.proc is None:
            return
        code = self.proc.poll()
        if code is None:
            return
        self._flush_queue_to_lines()
        if code == 0:
            self.state = "IDLE"
        else:
            self.state = "ERROR"
            self.errors += 1
        self._running = False
        self._stop_requested.set()

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

        self._drain_logs()

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
        for line in list(self.lines)[-body_h:]:
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
        status = f"Status: {self.state:<6} | Model: {self.model:<7} | Last run: {self.last_run:<5} | Errors: {self.errors:<3}"
        lines.append("│" + self._truncate(status, width - 2).ljust(width - 2) + "│")
        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines)

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self._stop_requested.set()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=1.0)

    def loop(self) -> None:
        key_reader = KeyReader()
        self.load_todo_if_changed()
        self.lines.append("> Ready. Press 'r' to run Codex, 's' to stop, 'q' to quit.")

        try:
            while True:
                self.load_todo_if_changed()
                self._check_process()
                self._flush_queue_to_lines()
                key = key_reader.get_key()
                if key:
                    k = key.lower()
                    if k == "q":
                        break
                    if k == "r" and self.state != "RUNNING":
                        self._start_codex()
                    if k == "s" and self.state == "RUNNING":
                        self.stop()
                        self.state = "IDLE"
                width, height = shutil.get_terminal_size(fallback=(100, 24))
                content = self._render(width, height)
                os.system("cls" if os.name == "nt" else "clear")
                print(content, end="", flush=True)
                time.sleep(self.refresh_delay)
        finally:
            self.stop()
            key_reader.close()
            self._log_file.close()


def main() -> None:
    todo_path = Path("AI_TODO.md")
    log_path = Path("logs") / "agent.log"
    cockpit = Cockpit(todo_path=todo_path, log_path=log_path)
    cockpit.loop()


if __name__ == "__main__":
    main()
