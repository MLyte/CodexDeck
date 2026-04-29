from __future__ import annotations

import os
import signal
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
from typing import Callable, Deque, Optional, Protocol, Sequence, TextIO


SENSITIVE_KEYS = ("token", "api_key", "apikey", "password", "secret")
CODEX_EXEC_OPTIONS_WITH_VALUE = {
    "-c",
    "--config",
    "-i",
    "--image",
    "-m",
    "--model",
    "--local-provider",
    "-p",
    "--profile",
    "-s",
    "--sandbox",
    "-C",
    "--cd",
    "--add-dir",
    "--output-schema",
    "--color",
    "-o",
    "--output-last-message",
    "--enable",
    "--disable",
}
CODEX_EXEC_PERSISTENCE_BLOCKERS = {"--ephemeral"}


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
    stdin: Optional[TextIO]

    def poll(self) -> Optional[int]:
        ...

    def terminate(self) -> None:
        ...

    def kill(self) -> None:
        ...

    def send_signal(self, sig: int) -> None:
        ...

    def wait(self, timeout: Optional[float] = None) -> int:
        ...


PopenFactory = Callable[..., ProcessHandle]


@dataclass(frozen=True)
class RunMetrics:
    runs_total: int
    runs_success: int
    runs_fail: int
    errors_total: int


@dataclass(frozen=True)
class RunStatus:
    state: RunnerState
    run_id: Optional[str]
    pid: Optional[int]
    returncode: Optional[int]
    errors: int
    last_error: Optional[str]
    running: bool
    uptime_seconds: Optional[float]
    duration_seconds: Optional[float]
    metrics: RunMetrics
    history: tuple[str, ...]
    codex_session_ready: bool = False
    codex_session_reused: bool = False


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
            for part in shlex.split(marked, posix=True)
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


def split_codex_exec_stdin_prompt(args: Sequence[str]) -> tuple[list[str], Optional[str]]:
    prepared = list(args)
    if len(prepared) < 3:
        return prepared, None
    executable = Path(prepared[0]).name.lower()
    if executable not in {"codex", "codex.exe"} or prepared[1] != "exec":
        return prepared, None
    if prepared[-1] == "-":
        return prepared, None
    if prepared[-1].startswith("-"):
        return prepared, None
    return [*prepared[:-1], "-"], prepared[-1]


def _codex_exec_prompt_index(args: Sequence[str]) -> Optional[int]:
    if len(args) < 3:
        return None
    executable = Path(args[0]).name.lower()
    if executable not in {"codex", "codex.exe"} or args[1] != "exec":
        return None

    index = 2
    while index < len(args):
        arg = args[index]
        if arg == "-":
            return index
        if arg == "--":
            return index + 1 if index + 1 < len(args) else None
        if not arg.startswith("-"):
            return index
        if arg in CODEX_EXEC_OPTIONS_WITH_VALUE:
            index += 2
            continue
        index += 1
    return None


def supports_codex_exec_resume(args: Sequence[str]) -> bool:
    prompt_index = _codex_exec_prompt_index(args)
    if prompt_index is None or prompt_index != len(args) - 1 or args[prompt_index] != "-":
        return False
    if any(
        arg == blocker or arg.startswith(f"{blocker}=")
        for arg in args[2:prompt_index]
        for blocker in CODEX_EXEC_PERSISTENCE_BLOCKERS
    ):
        return False
    return True


def build_codex_exec_resume_command(args: Sequence[str]) -> list[str]:
    prompt_index = _codex_exec_prompt_index(args)
    if prompt_index is None:
        return list(args)
    return [*args[:prompt_index], "resume", "--last", *args[prompt_index:]]


def codex_exec_session_key(args: Sequence[str]) -> tuple[str, ...] | None:
    prompt_index = _codex_exec_prompt_index(args)
    if prompt_index is None:
        return None
    return tuple(args[:prompt_index])


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
        self._finished_at: Optional[float] = None
        self._run_history: Deque[str] = deque(maxlen=50)
        self._state = RunnerState.IDLE
        self._returncode: Optional[int] = None
        self.errors = 0
        self.last_error: Optional[str] = None
        self._runs_total = 0
        self._runs_success = 0
        self._runs_fail = 0
        self._errors_total = 0
        self._can_resume_codex_session = False
        self._active_run_can_resume_codex_session = False
        self._active_run_reused_codex_session = False
        self._codex_session_key: tuple[str, ...] | None = None
        self._active_run_codex_session_key: tuple[str, ...] | None = None
        self._queued_resume_input: str | None = None

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
            self._finished_at = None
            self._run_history.clear()
            try:
                args = build_command(self.command, todo_path)
                args, stdin_prompt = split_codex_exec_stdin_prompt(args)
                can_use_codex_resume = supports_codex_exec_resume(args)
                session_key = codex_exec_session_key(args)
                self._active_run_can_resume_codex_session = can_use_codex_resume
                self._active_run_codex_session_key = session_key
                self._active_run_reused_codex_session = (
                    can_use_codex_resume
                    and self._can_resume_codex_session
                    and session_key == self._codex_session_key
                )
                if not self._active_run_reused_codex_session:
                    self._can_resume_codex_session = False
                    if session_key != self._codex_session_key:
                        self._codex_session_key = None
                if self._active_run_reused_codex_session:
                    args = build_codex_exec_resume_command(args)
                    if self._queued_resume_input is not None:
                        stdin_prompt = self._queued_resume_input
                        self._queued_resume_input = None
                popen_kwargs: dict[str, object] = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "stdin": subprocess.PIPE if stdin_prompt is not None else subprocess.DEVNULL,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "bufsize": 1,
                }
                if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                process = self._popen_factory(args, **popen_kwargs)
                if stdin_prompt is not None and process.stdin is not None:
                    process.stdin.write(stdin_prompt)
                    process.stdin.close()
            except Exception as exc:
                self._active_run_can_resume_codex_session = False
                self._active_run_reused_codex_session = False
                self._active_run_codex_session_key = None
                self._record_error_locked()
                self.last_error = f"POPEN_FAILED: {exc}"
                self._state = RunnerState.ERROR
                self._record_event_locked(f"error {self.last_error}")
                return self.status()

            self._process = process
            self._runs_total += 1
            self._state = RunnerState.RUNNING
            self._record_event_locked(f"started pid={process.pid}")
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
            self._record_event_locked("stopping")
            interrupted = self._interrupt_process_locked(process)
            terminated = False
            if not interrupted:
                self._record_event_locked("interrupt unavailable; terminating process", level="WARN")
                process.terminate()
                terminated = True

        killed = False
        try:
            returncode = process.wait(timeout=self.stop_timeout)
        except subprocess.TimeoutExpired:
            with self._lock:
                if interrupted:
                    self._record_event_locked(
                        f"interrupt timeout after {self.stop_timeout:.3f}s; terminating process",
                        level="WARN",
                    )
                else:
                    self._record_event_locked(
                        f"terminate timeout after {self.stop_timeout:.3f}s; killing process",
                        level="WARN",
                    )
            terminated = True
            if interrupted:
                process.terminate()
                try:
                    returncode = process.wait(timeout=self.stop_timeout)
                except subprocess.TimeoutExpired:
                    killed = True
                    with self._lock:
                        self._record_event_locked(
                            f"terminate timeout after {self.stop_timeout:.3f}s; killing process",
                            level="WARN",
                        )
                    process.kill()
                    returncode = process.wait(timeout=None)
            else:
                killed = True
                process.kill()
                returncode = process.wait(timeout=None)

        with self._lock:
            self._returncode = returncode
            self._join_reader_locked()
            self._process = None
            self._state = RunnerState.IDLE
            if killed:
                suffix = " after kill"
            elif terminated:
                suffix = " after terminate"
            elif interrupted:
                suffix = " after interrupt"
            else:
                suffix = ""
            self._finished_at = self._clock()
            if self._active_run_can_resume_codex_session:
                self._can_resume_codex_session = False
                self._active_run_reused_codex_session = False
                self._codex_session_key = None
                self._active_run_codex_session_key = None
            self._record_event_locked(f"stopped rc={returncode}{suffix}")
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
                self._record_error_locked()
                self._record_event_locked("RUN_TIMEOUT", level="ERROR")
                self.stop()
                self._state = RunnerState.ERROR
                self._record_failed_run_locked()
            return RunStatus(
                state=self._state,
                run_id=self._run_id,
                pid=self._process.pid if self._process is not None else None,
                returncode=self._returncode,
                errors=self.errors,
                last_error=self.last_error,
                running=self._is_running_locked(),
                uptime_seconds=self._uptime_locked(),
                duration_seconds=self._duration_locked(),
                metrics=RunMetrics(
                    runs_total=self._runs_total,
                    runs_success=self._runs_success,
                    runs_fail=self._runs_fail,
                    errors_total=self._errors_total,
                ),
                history=tuple(self._run_history),
                codex_session_ready=self._can_resume_codex_session,
                codex_session_reused=self._active_run_reused_codex_session,
            )

    def logs(self) -> list[str]:
        return self.log_buffer.lines()

    def send_input(self, text: str) -> bool:
        payload = text if text.endswith("\n") else f"{text}\n"
        with self._lock:
            if (
                self._process is None
                or self._process.stdin is None
                or getattr(self._process.stdin, "closed", False)
                or not self._is_running_locked()
            ):
                return False
            try:
                self._process.stdin.write(payload)
                self._process.stdin.flush()
            except Exception:
                self._record_error_locked()
                self.last_error = "PROCESS_INPUT_FAILED"
                self._record_event_locked(self.last_error, level="ERROR")
                return False
            return True

    def queue_next_resume_input(self, text: str) -> None:
        with self._lock:
            self._queued_resume_input = text

    def _is_running_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _finish_from_returncode_locked(self, returncode: int) -> None:
        if returncode == 0:
            self._state = RunnerState.IDLE
            self._finished_at = self._clock()
            self._runs_success += 1
            if self._active_run_can_resume_codex_session:
                self._can_resume_codex_session = True
                self._codex_session_key = self._active_run_codex_session_key
            self._record_event_locked("finished rc=0")
            return
        if self._active_run_can_resume_codex_session:
            self._can_resume_codex_session = False
            self._codex_session_key = None
        self._active_run_reused_codex_session = False
        self._active_run_codex_session_key = None
        self._record_error_locked()
        self.last_error = f"PROCESS_EXIT_NON_ZERO: {returncode}"
        self._state = RunnerState.ERROR
        self._finished_at = self._clock()
        self._record_failed_run_locked()
        self._record_event_locked(f"finished rc={returncode}", level="ERROR")

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
        if thread is not None and thread.is_alive():
            stdout = self._process.stdout if self._process is not None else None
            if stdout is not None and not stdout.closed:
                stdout.close()
            thread.join(timeout=1.0)
        if thread is None or not thread.is_alive():
            process = self._process
            self._reader_thread = None

    def _read_stdout(self, run_id: str, process: ProcessHandle) -> None:
        stdout = process.stdout
        if stdout is None:
            return
        try:
            for raw in stdout:
                line = str(raw).rstrip("\r\n")
                self._emit(f"[{run_id}] {line}")
        except (OSError, ValueError):
            return

    def _emit(self, message: str) -> None:
        stamped = f"{self._timestamp().isoformat(timespec='seconds')} {sanitize_log_message(message)}"
        self.log_buffer.append(stamped)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(stamped + "\n")

    def _uptime_locked(self) -> Optional[float]:
        if self._started_at is None or not self._is_running_locked():
            return None
        return max(0.0, self._clock() - self._started_at)

    def _duration_locked(self) -> Optional[float]:
        if self._started_at is None:
            return None
        if self._finished_at is not None:
            return max(0.0, self._finished_at - self._started_at)
        if self._is_running_locked():
            return max(0.0, self._clock() - self._started_at)
        return None

    def _record_error_locked(self) -> None:
        self.errors += 1
        self._errors_total += 1

    def _record_failed_run_locked(self) -> None:
        self._runs_fail += 1

    def _record_event_locked(self, event: str, *, level: str = "INFO") -> None:
        self._run_history.append(event)
        self._emit(f"[{level}] run {self._run_id} {event}")

    def _interrupt_process_locked(self, process: ProcessHandle) -> bool:
        send_signal = getattr(process, "send_signal", None)
        if send_signal is None:
            return False
        candidates: list[int] = []
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            candidates.append(signal.CTRL_BREAK_EVENT)
        candidates.append(signal.SIGINT)
        for signum in candidates:
            try:
                send_signal(signum)
            except (OSError, ValueError):
                continue
            self._record_event_locked(f"sent interrupt signal {signum}")
            return True
        return False
