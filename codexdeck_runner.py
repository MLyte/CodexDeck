from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Deque, Iterable, Optional, Protocol, Sequence, TextIO


SENSITIVE_KEYS = ("token", "api_key", "apikey", "password", "secret")


class RunnerState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class RunnerError(RuntimeError):
    error_code = "RUNNER_ERROR"


class ProcessAlreadyRunning(RunnerError):
    error_code = "PROCESS_ALREADY_RUNNING"


class ProcessNotRunning(RunnerError):
    error_code = "PROCESS_NOT_RUNNING"


class ProcessHandle(Protocol):
    pid: int
    stdout: Optional[TextIO]

    def poll(self) -> Optional[int]:
        ...

    def terminate(self) -> None:
        ...

    def kill(self) -> None:
        ...

    def wait(self, timeout: Optional[float] = None) -> int:
        ...


PopenFactory = Callable[..., ProcessHandle]


@dataclass(frozen=True)
class RunStatus:
    state: RunnerState
    run_id: Optional[str]
    pid: Optional[int]
    returncode: Optional[int]
    errors: int
    last_error: Optional[str]
    running: bool


class BoundedLogBuffer:
    def __init__(self, max_lines: int) -> None:
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")
        self._lines: Deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def __len__(self) -> int:
        with self._lock:
            return len(self._lines)


def sanitize_log_message(message: str) -> str:
    words = message.split()
    sanitized: list[str] = []
    mask_next = False
    for word in words:
        lowered = word.lower()
        if mask_next:
            sanitized.append("***")
            mask_next = False
            continue
        if any(key in lowered for key in SENSITIVE_KEYS):
            if "=" in word:
                key, sep, _value = word.partition("=")
                sanitized.append(f"{key}{sep}***")
            elif ":" in word:
                key, sep, _value = word.partition(":")
                sanitized.append(f"{key}{sep}***")
            else:
                sanitized.append(word)
                mask_next = True
            continue
        sanitized.append(word)
    return " ".join(sanitized)


def build_command(command: str | Sequence[str], todo_path: str | os.PathLike[str]) -> list[str]:
    todo = str(todo_path)
    placeholders = ("{todo}", "$TODO", "%TODO%")
    if isinstance(command, str):
        if not command.strip():
            raise ValueError("command must not be empty")
        has_placeholder = any(placeholder in command for placeholder in placeholders)
        marker = "__CODEXDECK_TODO_PLACEHOLDER__"
        marked = command.replace("{todo}", marker).replace("$TODO", marker).replace("%TODO%", marker)
        args = [
            part.replace(marker, todo)
            for part in shlex.split(marked, posix=os.name != "nt")
        ]
    else:
        has_placeholder = any(
            placeholder in str(part)
            for part in command
            for placeholder in placeholders
        )
        args = [
            str(part)
            .replace("{todo}", todo)
            .replace("$TODO", todo)
            .replace("%TODO%", todo)
            for part in command
        ]
    if not args:
        raise ValueError("command must not be empty")
    if not has_placeholder:
        args.append(todo)
    return args


class CodexProcessRunner:
    def __init__(
        self,
        command: str | Sequence[str],
        log_path: str | os.PathLike[str],
        *,
        popen_factory: Optional[PopenFactory] = None,
        max_log_lines: int = 500,
        stop_timeout: float = 2.0,
        run_timeout: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
        timestamp: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.command = command
        self.log_path = Path(log_path)
        self.log_buffer = BoundedLogBuffer(max_log_lines)
        self.stop_timeout = stop_timeout
        self.run_timeout = run_timeout
        self._popen_factory = popen_factory or subprocess.Popen
        self._clock = clock
        self._timestamp = timestamp
        self._lock = threading.RLock()
        self._process: Optional[ProcessHandle] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._run_id: Optional[str] = None
        self._started_at: Optional[float] = None
        self._state = RunnerState.IDLE
        self._returncode: Optional[int] = None
        self.errors = 0
        self.last_error: Optional[str] = None

    def start(self, todo_path: str | os.PathLike[str]) -> RunStatus:
        with self._lock:
            self._finalize_if_exited_locked()
            if self._is_running_locked():
                raise ProcessAlreadyRunning("a Codex process is already running")
            self._state = RunnerState.STARTING
            self._returncode = None
            self.last_error = None
            self._run_id = uuid.uuid4().hex
            self._started_at = self._clock()
            try:
                args = build_command(self.command, todo_path)
                process = self._popen_factory(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                self.errors += 1
                self.last_error = f"POPEN_FAILED: {exc}"
                self._state = RunnerState.ERROR
                self._emit(f"[ERROR] {self.last_error}")
                return self.status()

            self._process = process
            self._state = RunnerState.RUNNING
            self._emit(f"[INFO] run {self._run_id} started pid={process.pid}")
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                args=(self._run_id, process),
                name=f"codexdeck-log-reader-{self._run_id}",
                daemon=True,
            )
            self._reader_thread.start()
            return self.status()

    def stop(self) -> RunStatus:
        with self._lock:
            if not self._is_running_locked():
                raise ProcessNotRunning("no Codex process is running")
            process = self._process
            assert process is not None
            self._state = RunnerState.STOPPING
            self._emit(f"[INFO] run {self._run_id} stopping")
            process.terminate()

        killed = False
        try:
            returncode = process.wait(timeout=self.stop_timeout)
        except subprocess.TimeoutExpired:
            killed = True
            self._emit(f"[WARN] stop timeout after {self.stop_timeout:.3f}s; killing process")
            process.kill()
            returncode = process.wait(timeout=None)

        with self._lock:
            self._returncode = returncode
            self._join_reader_locked()
            self._process = None
            self._state = RunnerState.IDLE
            suffix = " after kill" if killed else ""
            self._emit(f"[INFO] run {self._run_id} stopped rc={returncode}{suffix}")
            return self.status()

    def wait(self, timeout: Optional[float] = None) -> RunStatus:
        with self._lock:
            process = self._process
            if process is None:
                return self.status()

        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return self.status()

        with self._lock:
            self._returncode = returncode
            self._join_reader_locked()
            self._process = None
            self._finish_from_returncode_locked(returncode)
            return self.status()

    def status(self) -> RunStatus:
        with self._lock:
            self._finalize_if_exited_locked()
            if (
                self.run_timeout is not None
                and self._is_running_locked()
                and self._started_at is not None
                and self._clock() - self._started_at >= self.run_timeout
            ):
                self.last_error = "RUN_TIMEOUT"
                self.errors += 1
                self._emit("[ERROR] RUN_TIMEOUT")
                self.stop()
                self._state = RunnerState.ERROR
            return RunStatus(
                state=self._state,
                run_id=self._run_id,
                pid=self._process.pid if self._process is not None else None,
                returncode=self._returncode,
                errors=self.errors,
                last_error=self.last_error,
                running=self._is_running_locked(),
            )

    def logs(self) -> list[str]:
        return self.log_buffer.lines()

    def _is_running_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _finish_from_returncode_locked(self, returncode: int) -> None:
        if returncode == 0:
            self._state = RunnerState.IDLE
            self._emit(f"[INFO] run {self._run_id} finished rc=0")
            return
        self.errors += 1
        self.last_error = f"PROCESS_EXIT_NON_ZERO: {returncode}"
        self._state = RunnerState.ERROR
        self._emit(f"[ERROR] run {self._run_id} finished rc={returncode}")

    def _finalize_if_exited_locked(self) -> None:
        if self._process is None:
            return
        returncode = self._process.poll()
        if returncode is None:
            return
        self._returncode = returncode
        self._join_reader_locked()
        self._process = None
        self._finish_from_returncode_locked(returncode)

    def _join_reader_locked(self) -> None:
        thread = self._reader_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._reader_thread = None

    def _read_stdout(self, run_id: str, process: ProcessHandle) -> None:
        stdout = process.stdout
        if stdout is None:
            return
        try:
            for raw in stdout:
                line = str(raw).rstrip("\r\n")
                self._emit(f"[{run_id}] {line}")
        except ValueError:
            return

    def _emit(self, message: str) -> None:
        stamped = f"{self._timestamp().isoformat(timespec='seconds')} {sanitize_log_message(message)}"
        self.log_buffer.append(stamped)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(stamped + "\n")
