from __future__ import annotations

import io
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
    def __init__(self, keys: list[str | None]) -> None:
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


def make_stub_config(tmp_path: Path) -> CockpitConfig:
    config = make_config(tmp_path)
    return CockpitConfig(
        todo_path=config.todo_path,
        log_path=config.log_path,
        codex_cmd="python3 tests/stubs/codex_stub.py --mode success {todo}",
        refresh_hz=config.refresh_hz,
    )


def test_loop_scrolls_todo_panel_with_navigation_keys(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("\n".join(f"- [ ] task {index}" for index in range(25)), encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader(["j", "j", "k", "PGDN", "q"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (80, 20),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert cockpit.task_offset == 5
    assert any("AI_TODO.md 6-9/25" in frame for frame in frames)
    assert key_reader.closed is True


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


def test_repeated_run_key_is_ignored_while_running(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "r", "r", "q"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 20),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 1
    assert not any("A run is already active" in line for line in runner.log_buffer.lines)
    assert any("[|" in frame or "[/" in frame or "[-" in frame or "[\\" in frame for frame in frames)


def test_loop_announces_and_marks_target_task(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_stub_config(tmp_path)
    config.todo_path.write_text(
        "\n".join(
            [
                "- [x] done task",
                "- [ ] first open task",
                "- [ ] second open task",
            ]
        ),
        encoding="utf-8",
    )
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "q"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 20),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert any("Target task: line 2: first open task" in line for line in runner.log_buffer.lines)
    assert any("Active mode: Stub Codex (simulation). No real Codex call will run." in line for line in runner.log_buffer.lines)
    assert any(">[ ] first open task" in frame for frame in frames)
    assert any("Stub Codex (simulation) is running on line 2: first open task." in frame for frame in frames)


def test_loop_guides_missing_todo_and_creates_skeleton_on_explicit_key(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.unlink()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "n", "q"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 20),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 0
    assert config.todo_path.exists()
    assert "Describe the first concrete action for Codex." in config.todo_path.read_text(encoding="utf-8")
    assert any("AI_TODO.md not found" in line for line in runner.log_buffer.lines)
    assert any("Starter AI_TODO.md created" in line for line in runner.log_buffer.lines)
    assert any("No AI_TODO.md" in frame for frame in frames)
    assert key_reader.closed is True


def test_loop_does_not_start_without_open_task(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [x] done\n", encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "q"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 20),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 0
    assert any("No open task" in line for line in runner.log_buffer.lines)
    assert any("All tasks are checked" in frame for frame in frames)
    assert key_reader.closed is True


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


def test_unix_screen_writer_clears_to_end_on_repaint() -> None:
    module = load_cockpit_module()
    stream = io.StringIO()
    sizes = [(120, 30), (80, 20)]

    def terminal_size() -> tuple[int, int]:
        return sizes.pop(0) if sizes else (80, 20)

    writer = module.DefaultScreenWriter(terminal_size=terminal_size, stream=stream, is_windows=False)

    writer("large frame")
    writer("small frame")

    output = stream.getvalue()
    assert output.startswith("\033[2J\033[Hlarge frame")
    assert "\033[H\033[Jsmall frame" in output


def test_display_logs_simplifies_runner_noise(tmp_path: Path) -> None:
    module = load_cockpit_module()
    cockpit = module.Cockpit(
        make_stub_config(tmp_path),
        key_reader_factory=lambda: FakeKeyReader(["q"]),
        screen_writer=lambda _content: None,
        runner=FakeRunner(),
    )

    visible = cockpit._display_logs(
        [
            "2026-04-29T10:18:17 [INFO] run abcdef1234567890abcdef1234567890 started pid=42987",
            "2026-04-29T10:18:17 [abcdef1234567890abcdef1234567890] codex_stub mode=success todo=/tmp/AI_TODO.md",
            "2026-04-29T10:18:17 [abcdef1234567890abcdef1234567890] stub success",
            "2026-04-29T10:18:17 [INFO] run abcdef1234567890abcdef1234567890 finished rc=0",
        ]
    )

    assert visible == [
        "Run started.",
        "Stub Codex (simulation) output: Simulation started.",
        "Stub Codex (simulation) output: stub success",
        "Run completed successfully.",
    ]


def test_loop_reclamps_task_offset_when_terminal_shrinks(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("\n".join(f"- [ ] task {index}" for index in range(60)), encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader([None, "q"])
    frames: list[str] = []
    sizes = [(100, 30), (79, 10)]

    def terminal_size() -> tuple[int, int]:
        return sizes.pop(0) if sizes else (79, 10)

    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=terminal_size,
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )
    cockpit.task_offset = 20

    cockpit.loop()

    assert cockpit.task_offset == 0
    assert any("compact mode" in frame for frame in frames)
    assert key_reader.closed is True
