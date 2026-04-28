from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from codexdeck_runner import CodexProcessRunner, sanitize_log_message


class FakeProcess:
    pid = 456

    def __init__(self) -> None:
        self.stdout = io.StringIO("one\ntwo\nthree\n")
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


def test_stdout_goes_to_bounded_queue_and_timestamped_log(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agent.log"
    process = FakeProcess()
    runner = CodexProcessRunner(
        ["codex"],
        log_path,
        popen_factory=lambda *a, **k: process,
        max_log_lines=3,
        timestamp=lambda: datetime(2026, 4, 29, 12, 30, 0),
    )

    runner.start(tmp_path / "AI_TODO.md")
    runner.wait()

    live_logs = runner.logs()
    file_logs = log_path.read_text(encoding="utf-8").splitlines()

    assert len(live_logs) == 3
    assert all(line.startswith("2026-04-29T12:30:00 ") for line in file_logs)
    assert any("one" in line for line in file_logs)
    assert any("three" in line for line in file_logs)
    assert "finished rc=0" in live_logs[-1]


def test_log_file_is_append_only_across_runs(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agent.log"

    for text in ("first\n", "second\n"):
        process = FakeProcess()
        process.stdout = io.StringIO(text)
        runner = CodexProcessRunner(
            ["codex"],
            log_path,
            popen_factory=lambda *a, process=process, **k: process,
            timestamp=lambda: datetime(2026, 4, 29, 12, 30, 0),
        )
        runner.start(tmp_path / "AI_TODO.md")
        runner.wait()

    content = log_path.read_text(encoding="utf-8")
    assert "first" in content
    assert "second" in content


def test_log_sanitization_masks_sensitive_values(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agent.log"
    process = FakeProcess()
    process.stdout = io.StringIO("token=abc123 password:super-secret api_key sk-test\n")
    runner = CodexProcessRunner(
        ["codex"],
        log_path,
        popen_factory=lambda *a, **k: process,
        timestamp=lambda: datetime(2026, 4, 29, 12, 30, 0),
    )

    runner.start(tmp_path / "AI_TODO.md")
    runner.wait()

    content = log_path.read_text(encoding="utf-8")
    assert "abc123" not in content
    assert "super-secret" not in content
    assert "sk-test" not in content
    assert "token=***" in content
    assert "password:***" in content
    assert "api_key ***" in content


def test_sanitize_log_message_leaves_unrelated_text_alone() -> None:
    assert sanitize_log_message("normal output line") == "normal output line"
