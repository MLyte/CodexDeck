from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from codexdeck_runner import (
    CodexProcessRunner,
    ProcessAlreadyRunning,
    RunnerState,
    build_codex_exec_resume_command,
    build_command,
    split_codex_exec_stdin_prompt,
    supports_codex_exec_resume,
)


class FakeStdin:
    def __init__(self) -> None:
        self.payload = ""
        self.closed = False
        self.flushed = False

    def write(self, text: str) -> int:
        self.payload += text
        return len(text)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 123,
        stdout: str = "",
        returncode: int | None = None,
        stdin: FakeStdin | None = None,
    ) -> None:
        self.pid = pid
        self.stdout = io.StringIO(stdout)
        self.stdin = stdin
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


def test_split_codex_exec_stdin_prompt_moves_final_prompt_to_stdin() -> None:
    args, stdin_prompt = split_codex_exec_stdin_prompt(
        ["codex", "exec", "--model", "gpt-5.4", "Read AI_TODO.md"]
    )

    assert args == ["codex", "exec", "--model", "gpt-5.4", "-"]
    assert stdin_prompt == "Read AI_TODO.md"


def test_split_codex_exec_stdin_prompt_keeps_existing_stdin_marker() -> None:
    args, stdin_prompt = split_codex_exec_stdin_prompt(["codex", "exec", "--model", "gpt-5.4", "-"])

    assert args == ["codex", "exec", "--model", "gpt-5.4", "-"]
    assert stdin_prompt is None


def test_codex_exec_resume_command_keeps_exec_options_before_resume() -> None:
    args = ["codex", "exec", "--model", "gpt-5.4", "--skip-git-repo-check", "-"]

    assert supports_codex_exec_resume(args) is True
    assert build_codex_exec_resume_command(args) == [
        "codex",
        "exec",
        "--model",
        "gpt-5.4",
        "--skip-git-repo-check",
        "resume",
        "--last",
        "-",
    ]


def test_codex_exec_resume_is_disabled_for_ephemeral_sessions() -> None:
    assert supports_codex_exec_resume(["codex", "exec", "--ephemeral", "-"]) is False


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
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL


def test_start_sends_codex_exec_prompt_through_stdin(tmp_path: Path) -> None:
    stdin = FakeStdin()
    process = FakeProcess(stdout="hello\n", returncode=None, stdin=stdin)
    seen: dict[str, object] = {}

    def factory(*args: object, **kwargs: object) -> FakeProcess:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return process

    runner = CodexProcessRunner(
        'codex exec --model gpt-5.4 "Read {todo}. Work on first task."',
        tmp_path / "logs" / "agent.log",
        popen_factory=factory,
    )

    runner.start(tmp_path / "AI_TODO.md")

    assert seen["args"][0] == ["codex", "exec", "--model", "gpt-5.4", "-"]
    assert seen["kwargs"]["stdin"] == subprocess.PIPE
    assert stdin.payload == f"Read {tmp_path / 'AI_TODO.md'}. Work on first task."
    assert stdin.closed is True


def test_successful_codex_exec_run_warms_next_run_with_resume(tmp_path: Path) -> None:
    processes = [
        FakeProcess(stdout="first\n", returncode=None, stdin=FakeStdin()),
        FakeProcess(stdout="second\n", returncode=None, stdin=FakeStdin()),
    ]
    seen_args: list[list[str]] = []

    def factory(*args: object, **kwargs: object) -> FakeProcess:
        seen_args.append(args[0])  # type: ignore[arg-type]
        return processes.pop(0)

    runner = CodexProcessRunner(
        'codex exec --model gpt-5.4 --skip-git-repo-check "Read {todo}. Work on first task."',
        tmp_path / "logs" / "agent.log",
        popen_factory=factory,
    )

    first = runner.start(tmp_path / "AI_TODO.md")
    runner.wait()
    second = runner.start(tmp_path / "AI_TODO.md")

    assert first.codex_session_reused is False
    assert runner.status().codex_session_reused is True
    assert second.codex_session_reused is True
    assert seen_args[0] == ["codex", "exec", "--model", "gpt-5.4", "--skip-git-repo-check", "-"]
    assert seen_args[1] == [
        "codex",
        "exec",
        "--model",
        "gpt-5.4",
        "--skip-git-repo-check",
        "resume",
        "--last",
        "-",
    ]


def test_codex_exec_resume_restarts_when_command_options_change(tmp_path: Path) -> None:
    processes = [
        FakeProcess(stdout="first\n", returncode=None, stdin=FakeStdin()),
        FakeProcess(stdout="second\n", returncode=None, stdin=FakeStdin()),
    ]
    seen_args: list[list[str]] = []

    def factory(*args: object, **kwargs: object) -> FakeProcess:
        seen_args.append(args[0])  # type: ignore[arg-type]
        return processes.pop(0)

    runner = CodexProcessRunner(
        'codex exec --model gpt-5.4 "Read {todo}."',
        tmp_path / "logs" / "agent.log",
        popen_factory=factory,
    )

    runner.start(tmp_path / "AI_TODO.md")
    runner.wait()
    runner.command = 'codex exec --model gpt-5.4-mini "Read {todo}."'
    status = runner.start(tmp_path / "AI_TODO.md")

    assert status.codex_session_reused is False
    assert seen_args[1] == ["codex", "exec", "--model", "gpt-5.4-mini", "-"]


def test_start_uses_batch_pipes_not_a_tty(tmp_path: Path) -> None:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text("- [ ] task\n", encoding="utf-8")
    runner = CodexProcessRunner(
        [sys.executable, "-c", "import sys; print(sys.stdout.isatty())"],
        tmp_path / "logs" / "agent.log",
    )

    runner.start(todo)
    status = runner.wait()

    assert status.returncode == 0
    assert any("False" in line for line in runner.logs())


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
