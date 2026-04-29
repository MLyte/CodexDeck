from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from codexdeck_core import CockpitConfig
from codexdeck_runner import ProcessNotRunning, RunnerState


def load_cockpit_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "agent-cockpit.py"
    spec = importlib.util.spec_from_file_location("agent_cockpit", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeStatus:
    state: RunnerState
    errors: int = 0


class FakeLogBuffer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append(self, line: str) -> None:
        self.lines.append(line)


class FakeRunner:
    def __init__(self) -> None:
        self.state = RunnerState.IDLE
        self.errors = 0
        self.log_buffer = FakeLogBuffer()
        self.started = 0
        self.stopped = 0

    def start(self, todo_path: Path) -> FakeStatus:
        assert todo_path.exists()
        self.started += 1
        self.state = RunnerState.RUNNING
        return self.status()

    def stop(self) -> FakeStatus:
        if self.state != RunnerState.RUNNING:
            raise ProcessNotRunning("no process")
        self.stopped += 1
        self.state = RunnerState.IDLE
        return self.status()

    def status(self) -> FakeStatus:
        return FakeStatus(state=self.state, errors=self.errors)

    def logs(self) -> list[str]:
        return self.log_buffer.lines


class FakeKeyReader:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.closed = False

    def get_key(self) -> str | None:
        if not self.keys:
            return None
        return self.keys.pop(0)

    def close(self) -> None:
        self.closed = True


def make_config(tmp_path: Path) -> CockpitConfig:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text("- [ ] task\n", encoding="utf-8")
    return CockpitConfig(
        todo_path=todo,
        log_path=tmp_path / "logs" / "agent.log",
        codex_cmd="fake {todo}",
        refresh_hz=1000.0,
    )


def test_loop_uses_fake_key_reader_without_blocking(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "s", "x", "h", "?", "l", "q"])
    frames: list[str] = []
    sleeps: list[float] = []
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (79, 10),
        sleeper=sleeps.append,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 1
    assert runner.stopped == 1
    assert key_reader.closed is True
    assert frames
    assert sleeps
    assert any("Ignored key" in line for line in runner.log_buffer.lines)
    assert any("Reloaded AI_TODO.md" in line for line in runner.log_buffer.lines)


def test_loop_closes_key_reader_after_render_exception(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader([])
    calls = 0

    def terminal_size() -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("terminal failed")
        return (80, 20)

    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=terminal_size,
        sleeper=lambda _delay: None,
        screen_writer=lambda _content: None,
        runner=runner,
    )

    with pytest.raises(RuntimeError, match="terminal failed"):
        cockpit.loop()

    assert key_reader.closed is True
