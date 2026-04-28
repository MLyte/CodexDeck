from __future__ import annotations

import sys
from pathlib import Path

from codexdeck_runner import CodexProcessRunner, RunnerState


STUB = Path(__file__).parents[1] / "stubs" / "codex_stub.py"


def test_stub_success(tmp_path: Path) -> None:
    runner = CodexProcessRunner(
        [sys.executable, str(STUB), "--mode", "success", "{todo}"],
        tmp_path / "logs" / "agent.log",
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.wait(timeout=5)

    assert status.state == RunnerState.IDLE
    assert status.errors == 0
    assert "stub success" in (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")


def test_stub_fail(tmp_path: Path) -> None:
    runner = CodexProcessRunner(
        [sys.executable, str(STUB), "--mode", "fail", "{todo}"],
        tmp_path / "logs" / "agent.log",
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.wait(timeout=5)

    assert status.state == RunnerState.ERROR
    assert status.errors == 1
    assert "[ERROR] stub fail" in (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")


def test_stub_sleep_can_be_stopped(tmp_path: Path) -> None:
    runner = CodexProcessRunner(
        [sys.executable, str(STUB), "--mode", "sleep", "--delay", "0.05", "{todo}"],
        tmp_path / "logs" / "agent.log",
        stop_timeout=1,
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.stop()

    assert status.state == RunnerState.IDLE
    assert status.running is False


def test_stub_spam_keeps_bounded_queue(tmp_path: Path) -> None:
    runner = CodexProcessRunner(
        [sys.executable, str(STUB), "--mode", "spam", "--lines", "100", "{todo}"],
        tmp_path / "logs" / "agent.log",
        max_log_lines=10,
    )

    runner.start(tmp_path / "AI_TODO.md")
    status = runner.wait(timeout=5)

    assert status.state == RunnerState.IDLE
    assert len(runner.logs()) == 10
    assert "spam line 0099" in (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")
