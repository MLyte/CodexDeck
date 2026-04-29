from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path

import pytest

from codexdeck_runner import (
    CodexProcessRunner,
    ProcessAlreadyRunning,
    RunnerState,
    build_command,
)


class FakeProcess:
    def __init__(self, *, pid: int = 123, stdout: str = "", returncode: int | None = None) -> None:
        self.pid = pid
        self.stdout = io.StringIO(stdout)
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.signals: list[int] = []
        self.wait_calls = 0
        self.wait_timeout_once = False
        self.wait_timeouts = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.wait_timeouts > 0:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("fake", timeout)
        if self.wait_timeout_once and not self.killed:
            self.wait_timeout_once = False
            raise subprocess.TimeoutExpired("fake", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_build_command_replaces_todo_placeholders(tmp_path: Path) -> None:
    todo = tmp_path / "AI TODO.md"

    assert build_command("python stub.py --mode success {todo}", todo)[-1] == str(todo)
    assert build_command(["python", "stub.py", "$TODO"], todo)[-1] == str(todo)
    assert build_command(["python", "stub.py", "%TODO%"], todo)[-1] == str(todo)


def test_build_command_appends_todo_when_placeholder_is_absent(tmp_path: Path) -> None:
    todo = tmp_path / "AI_TODO.md"

    assert build_command("codex run", todo) == ["codex", "run", str(todo)]
    assert build_command(["codex", "run"], todo) == ["codex", "run", str(todo)]


def test_start_success_uses_popen_factory(tmp_path: Path) -> None:
    process = FakeProcess(stdout="hello\n", returncode=None)
    seen: dict[str, object] = {}

    def factory(*args: object, **kwargs: object) -> FakeProcess:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return process

    runner = CodexProcessRunner(["codex", "{todo}"], tmp_path / "logs" / "agent.log", popen_factory=factory)

    status = runner.start(tmp_path / "AI_TODO.md")

    assert status.state == RunnerState.RUNNING
    assert status.pid == 123
    assert seen["args"][0] == ["codex", str(tmp_path / "AI_TODO.md")]
    assert seen["kwargs"]["text"] is True


def test_rejects_second_process(tmp_path: Path) -> None:
    runner = CodexProcessRunner(
        ["codex", "{todo}"],
        tmp_path / "agent.log",
        popen_factory=lambda *args, **kwargs: FakeProcess(returncode=None),
    )

    runner.start(tmp_path / "AI_TODO.md")

    with pytest.raises(ProcessAlreadyRunning):
        runner.start(tmp_path / "AI_TODO.md")


def test_popen_exception_is_counted(tmp_path: Path) -> None:
    def factory(*args: object, **kwargs: object) -> FakeProcess:
        raise OSError("missing codex")

    runner = CodexProcessRunner(["codex", "{todo}"], tmp_path / "agent.log", popen_factory=factory)

    status = runner.start(tmp_path / "AI_TODO.md")

    assert status.state == RunnerState.ERROR
    assert status.errors == 1
    assert status.last_error == "POPEN_FAILED: missing codex"


def test_wait_success_returns_idle(tmp_path: Path) -> None:
    process = FakeProcess(stdout="done\n", returncode=None)
    runner = CodexProcessRunner(["codex"], tmp_path / "agent.log", popen_factory=lambda *a, **k: process)

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.wait()

    assert status.state == RunnerState.IDLE
    assert status.returncode == 0
    assert status.errors == 0
    assert status.duration_seconds is not None
    assert status.metrics.runs_total == 1
    assert status.metrics.runs_success == 1
    assert status.metrics.runs_fail == 0
    assert runner._reader_thread is None


def test_wait_non_zero_is_counted(tmp_path: Path) -> None:
    process = FakeProcess(stdout="[ERROR] nope\n", returncode=7)
    runner = CodexProcessRunner(["codex"], tmp_path / "agent.log", popen_factory=lambda *a, **k: process)

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.wait()

    assert status.state == RunnerState.ERROR
    assert status.returncode == 7
    assert status.errors == 1
    assert status.last_error == "PROCESS_EXIT_NON_ZERO: 7"
    assert status.metrics.runs_total == 1
    assert status.metrics.runs_success == 0
    assert status.metrics.runs_fail == 1
    assert status.metrics.errors_total == 1


def test_stop_terminates_process(tmp_path: Path) -> None:
    process = FakeProcess(returncode=None)
    runner = CodexProcessRunner(["codex"], tmp_path / "agent.log", popen_factory=lambda *a, **k: process)

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.stop()

    assert process.signals
    assert process.terminated is False
    assert process.killed is False
    assert status.state == RunnerState.IDLE
    assert runner._reader_thread is None


def test_stop_terminates_immediately_when_interrupt_is_unavailable(tmp_path: Path) -> None:
    process = FakeProcess(returncode=None)
    process.send_signal = None  # type: ignore[method-assign]
    runner = CodexProcessRunner(["codex"], tmp_path / "agent.log", popen_factory=lambda *a, **k: process)

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.stop()

    assert process.terminated is True
    assert process.killed is False
    assert status.state == RunnerState.IDLE


def test_stop_terminates_after_interrupt_timeout(tmp_path: Path) -> None:
    process = FakeProcess(returncode=None)
    process.wait_timeout_once = True
    runner = CodexProcessRunner(
        ["codex"],
        tmp_path / "agent.log",
        popen_factory=lambda *a, **k: process,
        stop_timeout=0.001,
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.stop()

    assert process.signals
    assert process.terminated is True
    assert process.killed is False
    assert status.state == RunnerState.IDLE
    assert status.returncode == 0
    assert runner._reader_thread is None


def test_stop_kills_after_interrupt_and_terminate_timeout(tmp_path: Path) -> None:
    process = FakeProcess(returncode=None)
    process.wait_timeouts = 2
    runner = CodexProcessRunner(
        ["codex"],
        tmp_path / "agent.log",
        popen_factory=lambda *a, **k: process,
        stop_timeout=0.001,
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.stop()

    assert process.signals
    assert process.terminated is True
    assert process.killed is True
    assert status.state == RunnerState.IDLE
    assert status.returncode == -9
    assert runner._reader_thread is None


def test_run_timeout_is_counted(tmp_path: Path) -> None:
    now = [0.0]
    process = FakeProcess(returncode=None)
    runner = CodexProcessRunner(
        ["codex"],
        tmp_path / "agent.log",
        popen_factory=lambda *a, **k: process,
        run_timeout=1.0,
        clock=lambda: now[0],
    )

    runner.start(tmp_path / "AI_TODO.md")
    now[0] = 2.0
    status = runner.status()

    assert status.state == RunnerState.ERROR
    assert status.errors == 1
    assert status.last_error == "RUN_TIMEOUT"
    assert status.metrics.runs_total == 1
    assert status.metrics.runs_fail == 1
    assert status.metrics.errors_total == 1
    assert runner._reader_thread is None


def test_status_exposes_current_uptime_and_history(tmp_path: Path) -> None:
    now = [10.0]
    process = FakeProcess(returncode=None)
    runner = CodexProcessRunner(
        ["codex"],
        tmp_path / "agent.log",
        popen_factory=lambda *a, **k: process,
        clock=lambda: now[0],
    )

    started = runner.start(tmp_path / "AI_TODO.md")
    now[0] = 12.5
    status = runner.status()

    assert started.uptime_seconds == 0.0
    assert status.uptime_seconds == 2.5
    assert status.duration_seconds == 2.5
    assert status.metrics.runs_total == 1
    assert any("started pid=123" in event for event in status.history)
