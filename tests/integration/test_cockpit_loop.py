from __future__ import annotations

import io
import importlib.util
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from codexdeck_core import CockpitConfig
from codexdeck_runner import CodexProcessRunner
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
    run_id: str | None = None
    returncode: int | None = None
    duration_seconds: float | None = None


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
        self.command = "fake {todo}"
        self.started_command = ""

    def start(self, todo_path: Path) -> FakeStatus:
        assert todo_path.exists()
        self.started += 1
        self.started_command = self.command
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


class AutoCompletingRunner(FakeRunner):
    def __init__(self, *, todo_path: Path, mark_first_task_done: bool) -> None:
        super().__init__()
        self.todo_path = todo_path
        self.mark_first_task_done = mark_first_task_done
        self._active_run_id: str | None = None
        self._completed_run_id: str | None = None
        self._completed_returncode: int | None = None
        self._running_status_reads = 0

    def start(self, todo_path: Path) -> FakeStatus:
        status = super().start(todo_path)
        self._active_run_id = f"run-{self.started}"
        self._completed_run_id = None
        self._completed_returncode = None
        self._running_status_reads = 0
        return FakeStatus(state=status.state, errors=status.errors, run_id=self._active_run_id)

    def status(self) -> FakeStatus:
        if self.state == RunnerState.RUNNING:
            self._running_status_reads += 1
            if self.started == 1 and self._running_status_reads >= 2:
                self.state = RunnerState.IDLE
                self._completed_run_id = self._active_run_id
                self._completed_returncode = 0
                if self.mark_first_task_done:
                    self.todo_path.write_text("- [x] first task\n- [ ] second task\n", encoding="utf-8")
            else:
                return FakeStatus(state=RunnerState.RUNNING, run_id=self._active_run_id)
        return FakeStatus(
            state=self.state,
            run_id=self._completed_run_id,
            returncode=self._completed_returncode,
            duration_seconds=0.1 if self._completed_returncode is not None else None,
        )


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


class FakeScreenWriter:
    def __init__(self) -> None:
        self.frames: list[str] = []
        self.closed = 0

    def __call__(self, frame: str) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed += 1


class BlockingStopRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.stop_started = threading.Event()
        self.release_stop = threading.Event()

    def stop(self) -> FakeStatus:
        if self.state != RunnerState.RUNNING:
            raise ProcessNotRunning("no process")
        self.stopped += 1
        self.state = RunnerState.STOPPING
        self.stop_started.set()
        assert self.release_stop.wait(timeout=1), "stop was not released by the UI loop"
        self.state = RunnerState.IDLE
        return self.status()


class StopReleaseKeyReader(FakeKeyReader):
    def __init__(self, runner: BlockingStopRunner) -> None:
        super().__init__(["r", "s"])
        self.runner = runner
        self.stop_confirmed = False
        self.quit_sent = False
        self.confirm_sent = False

    def get_key(self) -> str | None:
        key = super().get_key()
        if key is not None:
            return key
        if not self.stop_confirmed:
            self.stop_confirmed = True
            return "y"
        if self.runner.stop_started.is_set() and not self.quit_sent:
            self.quit_sent = True
            return "q"
        if self.quit_sent and not self.confirm_sent:
            self.confirm_sent = True
            self.runner.release_stop.set()
            return "y"
        return None


def make_config(tmp_path: Path) -> CockpitConfig:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text("- [ ] task\n", encoding="utf-8")
    return CockpitConfig(
        todo_path=todo,
        log_path=tmp_path / "logs" / "agent.log",
        user_log_path=tmp_path / "logs" / "user.log",
        codex_cmd="fake {todo}",
        model="normal",
        models=("normal", "codex-plus"),
        fast_model="fast",
        permissions=("default", "workspace-write"),
        refresh_hz=1000.0,
    )


def make_stub_config(tmp_path: Path) -> CockpitConfig:
    config = make_config(tmp_path)
    return CockpitConfig(
        todo_path=config.todo_path,
        log_path=config.log_path,
        user_log_path=config.user_log_path,
        codex_cmd="python3 tests/stubs/codex_stub.py --mode success {todo}",
        refresh_hz=config.refresh_hz,
    )


def test_loop_scrolls_todo_panel_with_navigation_keys(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("\n".join(f"- [ ] task {index}" for index in range(25)), encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader(["DOWN", "DOWN", "UP", "PGDN", "PGUP", "q", "y"])
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

    assert cockpit.task_offset == 1
    assert any("AI_TODO.md 6-9/25" in frame for frame in frames)
    assert any("AI_TODO.md 2-5/25" in frame for frame in frames)
    assert key_reader.closed is True


def test_posix_key_reader_decodes_page_navigation_without_stray_suffix() -> None:
    module = load_cockpit_module()

    assert module.KeyReader._decode_posix_key("\x1b[5~") == "PGUP"
    assert module.KeyReader._decode_posix_key("\x1b[6~") == "PGDN"
    assert module.KeyReader._decode_posix_key("\x1b[A") == "UP"
    assert module.KeyReader._decode_posix_key("j") == "j"


def test_posix_key_reader_decodes_batched_arrow_sequences() -> None:
    module = load_cockpit_module()

    keys, remainder = module.KeyReader._decode_posix_keys("\x1b[B\x1b[B\x1b[B\x1b")

    assert keys == ["DOWN", "DOWN", "DOWN"]
    assert remainder == "\x1b"


def test_loop_uses_fake_key_reader_without_blocking(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "s", "y", "x", "h", "?", "l", "q", "y"])
    frames: list[str] = []
    sleeps: list[float] = []
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 24),
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
    assert any("Help: CodexDeck keeps AI_TODO.md visible" in frame for frame in frames)
    assert any("GitHub: https://github.com/MLyte/CodexDeck" in frame for frame in frames)


def test_stop_key_does_not_block_tui_while_runner_is_stopping(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = BlockingStopRunner()
    key_reader = StopReleaseKeyReader(runner)
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
    assert runner.stopped == 1
    assert key_reader.stop_confirmed is True
    assert key_reader.quit_sent is True
    assert key_reader.confirm_sent is True
    assert key_reader.closed is True
    assert any("Stop Codex? Press y to confirm" in frame for frame in frames)
    assert any("Stop requested." in frame for frame in frames)


def test_sleep_stub_stops_from_tui_without_freezing(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    stub_path = Path(__file__).resolve().parents[1] / "stubs" / "codex_stub.py"
    config = CockpitConfig(
        todo_path=config.todo_path,
        log_path=config.log_path,
        user_log_path=config.user_log_path,
        codex_cmd=f"{sys.executable} {stub_path} --mode sleep --delay 0.01 {{todo}}",
        refresh_hz=1000.0,
        stop_timeout=0.5,
    )
    runner = CodexProcessRunner(config.codex_cmd, config.log_path, stop_timeout=config.stop_timeout)
    frames: list[str] = []

    class SleepStopKeyReader(FakeKeyReader):
        def __init__(self) -> None:
            super().__init__(["r"])
            self.stop_sent = False
            self.quit_sent = False
            self.confirm_sent = False

        def get_key(self) -> str | None:
            key = super().get_key()
            if key is not None:
                return key
            logs = runner.logs()
            if not self.stop_sent and any("stub sleeping" in line for line in logs):
                self.stop_sent = True
                return "s"
            if self.stop_sent and not self.confirm_sent:
                self.confirm_sent = True
                return "y"
            if self.stop_sent and not self.quit_sent and not cockpit._status_running(runner.status()):
                self.quit_sent = True
                return "q"
            if self.quit_sent:
                return "y"
            return None

    key_reader = SleepStopKeyReader()
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 24),
        sleeper=lambda _delay: time.sleep(0.01),
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    status = runner.status()
    assert key_reader.stop_sent is True
    assert key_reader.quit_sent is True
    assert key_reader.confirm_sent is True
    assert key_reader.closed is True
    assert status.state == RunnerState.IDLE
    assert status.pid is None
    assert cockpit._stop_thread is None or not cockpit._stop_thread.is_alive()
    assert len(frames) >= 3
    assert any("Stop requested." in line for line in runner.logs())
    assert any("stopped rc=" in line for line in runner.logs())


def test_stop_confirmation_can_be_cancelled(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "s", "n", "q", "y"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 1
    assert runner.stopped == 1
    assert any("Stop Codex? Press y to confirm" in frame for frame in frames)
    assert any("Stop cancelled." in line for line in runner.log_buffer.lines)
    assert "stop cancelled" in cockpit.config.user_log_path.read_text(encoding="utf-8")


def test_loop_reload_key_refreshes_visible_tasks_and_summary(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [ ] old task\n", encoding="utf-8")
    runner = FakeRunner()
    frames: list[str] = []

    class EditingKeyReader(FakeKeyReader):
        def get_key(self) -> str | None:
            key = super().get_key()
            if key == "l":
                config.todo_path.write_text("- [x] old task\n- [ ] new task\n", encoding="utf-8")
            return key

    key_reader = EditingKeyReader([None, "l", "q", "y"])
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert any(" [ ] old task" in frame and "Tasks: 0 done | 1 open | 1 total" in frame for frame in frames)
    assert any(" [x] old task" in frame and " [ ] new task" in frame for frame in frames)
    assert any("Target: line 2: new task" in frame for frame in frames)
    assert any("Tasks: 1 done | 1 open | 2 total" in frame for frame in frames)
    assert any("Reloaded AI_TODO.md" in line for line in runner.log_buffer.lines)
    assert key_reader.closed is True


def test_edit_key_opens_todo_in_terminal_editor_and_reloads(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [ ] old task\n", encoding="utf-8")
    runner = FakeRunner()
    first_reader = FakeKeyReader(["e"])
    second_reader = FakeKeyReader(["q", "y"])
    readers = [first_reader, second_reader]
    screen_writer = FakeScreenWriter()

    def key_reader_factory() -> FakeKeyReader:
        assert readers
        return readers.pop(0)

    def editor_runner(todo_path: Path) -> int:
        todo_path.write_text("- [x] old task\n- [ ] edited in nano\n", encoding="utf-8")
        return 0

    cockpit = module.Cockpit(
        config,
        key_reader_factory=key_reader_factory,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=screen_writer,
        runner=runner,
        editor_runner=editor_runner,
    )

    cockpit.loop()

    assert first_reader.closed is True
    assert second_reader.closed is True
    assert screen_writer.closed >= 1
    assert any("Back from nano. AI_TODO.md closed." in line for line in runner.log_buffer.lines)
    assert any(" [x] old task" in frame and " [ ] edited in nano" in frame for frame in screen_writer.frames)
    user_log = config.user_log_path.read_text(encoding="utf-8")
    assert "editor opened" in user_log
    assert "editor closed" in user_log


def test_log_key_opens_run_summary_markdown(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    runner = FakeRunner()
    first_reader = FakeKeyReader(["g"])
    second_reader = FakeKeyReader(["q", "y"])
    readers = [first_reader, second_reader]
    opened_paths: list[Path] = []

    def key_reader_factory() -> FakeKeyReader:
        assert readers
        return readers.pop(0)

    def editor_runner(path: Path) -> int:
        opened_paths.append(path)
        return 0

    cockpit = module.Cockpit(
        config,
        key_reader_factory=key_reader_factory,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=lambda _frame: None,
        runner=runner,
        editor_runner=editor_runner,
    )

    cockpit.loop()

    assert opened_paths == [tmp_path / "CODEX_RUNS.md"]
    assert (tmp_path / "CODEX_RUNS.md").read_text(encoding="utf-8").startswith("# Codex Run Log")
    assert any("Opening CODEX_RUNS.md in nano" in line for line in runner.log_buffer.lines)
    assert first_reader.closed is True
    assert second_reader.closed is True


def test_quit_requires_confirmation_and_can_be_cancelled(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["q", "n", "q", "y"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert any("Quit CodexDeck? Press y to confirm" in frame for frame in frames)
    assert any("Quit cancelled" in line for line in runner.log_buffer.lines)
    assert key_reader.closed is True


def test_loop_keyboard_commands_cycle_runtime_options(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    runner = FakeRunner()
    key_reader = FakeKeyReader(["m", "f", "p", "r", "q", "y"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert cockpit.model == "codex-plus"
    assert cockpit.fast_mode is True
    assert cockpit.permission == "workspace-write"
    assert any("(M)odel: fast" in frame and "(Pe)rm: workspace-write" in frame for frame in frames)
    user_log = config.user_log_path.read_text(encoding="utf-8")
    assert "model selected | model=codex-plus" in user_log
    assert "fast mode on | model=fast" in user_log
    assert "permission selected | permission=workspace-write" in user_log


def test_new_task_input_saves_typed_text_with_ctrl_s(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    runner = FakeRunner()
    keys = ["n", *list("Write the README update"), "\x13", "q", "y"]
    key_reader = FakeKeyReader(keys)
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    todo_text = config.todo_path.read_text(encoding="utf-8")
    assert "- [ ] Write the README update" in todo_text
    assert any("New task: Write the README" in frame for frame in frames)
    assert any("New task saved to AI_TODO.md" in line for line in runner.log_buffer.lines)
    assert "task added | text=Write the README update" in config.user_log_path.read_text(encoding="utf-8")


def test_new_task_input_can_be_cancelled_with_escape(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    original_todo = config.todo_path.read_text(encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader(["n", *list("discard me"), "\x1b", "q", "y"])
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=lambda _frame: None,
        runner=runner,
    )

    cockpit.loop()

    assert config.todo_path.read_text(encoding="utf-8") == original_todo
    assert any("New task cancelled" in line for line in runner.log_buffer.lines)
    assert "task input cancelled" in config.user_log_path.read_text(encoding="utf-8")


def test_runtime_options_fill_command_placeholders_on_next_run(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config = CockpitConfig(
        todo_path=config.todo_path,
        log_path=config.log_path,
        user_log_path=config.user_log_path,
        codex_cmd="codex --model {model} --permission {permission} --fast {fast} {todo}",
        model="normal",
        models=("normal", "codex-plus"),
        fast_model="fast",
        permission="default",
        permissions=("default", "workspace-write"),
        refresh_hz=config.refresh_hz,
    )
    runner = FakeRunner()
    key_reader = FakeKeyReader(["m", "f", "p", "r", "q", "y"])
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=lambda _frame: None,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started_command == "codex --model fast --permission workspace-write --fast 1 {todo}"


def test_auto_mode_pauses_when_completed_run_leaves_same_task_open(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    runner = AutoCompletingRunner(todo_path=config.todo_path, mark_first_task_done=False)
    key_reader = FakeKeyReader(["o", "r", None, "q", "y"])
    frames: list[str] = []
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 1
    assert cockpit.auto_mode is False
    assert any("Auto mode paused. The previous task is still open." in line for line in runner.log_buffer.lines)
    assert "auto mode paused | reason=previous task still open" in config.user_log_path.read_text(encoding="utf-8")
    assert any("Auto: on" in frame for frame in frames)


def test_auto_mode_starts_next_task_after_successful_checked_off_run(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    runner = AutoCompletingRunner(todo_path=config.todo_path, mark_first_task_done=True)
    key_reader = FakeKeyReader(["o", "r", None, "q", "y"])
    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (120, 24),
        sleeper=lambda _delay: None,
        screen_writer=lambda _frame: None,
        runner=runner,
    )

    cockpit.loop()

    assert runner.started == 2
    assert any("Auto mode starting next task: line 2: second task." in line for line in runner.log_buffer.lines)
    user_log = config.user_log_path.read_text(encoding="utf-8")
    assert "auto mode on" in user_log
    assert "auto next task | target=line 2: second task" in user_log


def test_repeated_run_key_is_ignored_while_running(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "r", "r", "q", "y"])
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
    key_reader = FakeKeyReader(["r", "q", "y"])
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
    assert any("Stub Codex (simulation) is running on line 2" in frame for frame in frames)


def test_short_stub_output_keeps_active_marker_on_first_open_task(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    stub_path = Path(__file__).resolve().parents[1] / "stubs" / "codex_stub.py"
    config = CockpitConfig(
        todo_path=config.todo_path,
        log_path=config.log_path,
        user_log_path=config.user_log_path,
        codex_cmd=f"{sys.executable} {stub_path} --mode success {{todo}}",
        refresh_hz=1000.0,
    )
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
    runner = CodexProcessRunner(config.codex_cmd, config.log_path)
    key_reader = FakeKeyReader(["r", None, None, "q", "y"])
    frames: list[str] = []

    cockpit = module.Cockpit(
        config,
        key_reader_factory=lambda: key_reader,
        terminal_size=lambda: (100, 24),
        sleeper=lambda _delay: time.sleep(0.05),
        screen_writer=frames.append,
        runner=runner,
    )

    cockpit.loop()

    matching_frames = [
        frame
        for frame in frames
        if ">[ ] first open task" in frame and "Stub Codex (simulation) output: stub success" in frame
    ]
    assert matching_frames
    lines = matching_frames[0].splitlines()
    task_index = next(index for index, line in enumerate(lines) if ">[ ] first open task" in line)
    output_title_index = next(index for index, line in enumerate(lines) if "Codex Output" in line)
    stub_output_index = next(
        index for index, line in enumerate(lines) if "Stub Codex (simulation) output: stub success" in line
    )
    assert task_index < output_title_index < stub_output_index
    user_log = config.user_log_path.read_text(encoding="utf-8")
    assert "run started | target=line 2: first open task" in user_log
    assert "run completed | target=line 2: first open task" in user_log
    run_summary = (config.todo_path.parent / "CODEX_RUNS.md").read_text(encoding="utf-8")
    assert "## " in run_summary
    assert "- Task: line 2: first open task" in run_summary
    assert "- Result: completed" in run_summary
    assert "- Model: gpt-5.5" in run_summary


def test_loop_guides_missing_todo_and_saves_first_typed_task(tmp_path: Path) -> None:
    module = load_cockpit_module()
    missing_todo = tmp_path / "missing" / "AI_TODO.md"
    config = CockpitConfig.from_env(
        {
            "CODEX_TODO_PATH": str(missing_todo),
            "CODEX_LOG_PATH": str(tmp_path / "logs" / "agent.log"),
            "CODEX_CMD": "fake {todo}",
            "CODEX_MODEL": "normal",
            "CODEX_MODELS": "normal,codex-plus",
            "CODEX_FAST_MODEL": "fast",
            "CODEX_PERMISSIONS": "default,workspace-write",
            "STATE_REFRESH_HZ": "1000",
        },
        base_dir=tmp_path,
    )
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "n", *list("First concrete task"), "\x13", "q", "y"])
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
    assert config.todo_path == missing_todo
    assert missing_todo.exists()
    assert "- [ ] First concrete task" in missing_todo.read_text(encoding="utf-8")
    assert any("AI_TODO.md not found" in line for line in runner.log_buffer.lines)
    assert any("New task saved to AI_TODO.md" in line for line in runner.log_buffer.lines)
    assert any("No AI_TODO.md" in frame for frame in frames)
    assert "task added | text=First concrete task" in config.user_log_path.read_text(encoding="utf-8")
    assert key_reader.closed is True


def test_loop_does_not_start_without_open_task(tmp_path: Path) -> None:
    module = load_cockpit_module()
    config = make_config(tmp_path)
    config.todo_path.write_text("- [x] done\n", encoding="utf-8")
    runner = FakeRunner()
    key_reader = FakeKeyReader(["r", "q", "y"])
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
    assert output.startswith("\033[?1049h\033[2J\033[Hlarge frame")
    assert "\033[H\033[Jsmall frame" in output


def test_unix_screen_writer_restores_main_screen_on_close() -> None:
    module = load_cockpit_module()
    stream = io.StringIO()
    writer = module.DefaultScreenWriter(
        terminal_size=lambda: (100, 20),
        stream=stream,
        is_windows=False,
    )

    writer("frame")
    writer.close()

    output = stream.getvalue()
    assert output.startswith("\033[?1049h")
    assert output.endswith("\033[?1049l")


def test_loop_closes_screen_writer_when_available(tmp_path: Path) -> None:
    module = load_cockpit_module()
    runner = FakeRunner()
    key_reader = FakeKeyReader(["q", "y"])

    class ClosableWriter:
        def __init__(self) -> None:
            self.closed = False

        def __call__(self, _content: str) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    writer = ClosableWriter()
    cockpit = module.Cockpit(
        make_config(tmp_path),
        key_reader_factory=lambda: key_reader,
        screen_writer=writer,
        runner=runner,
    )

    cockpit.loop()

    assert writer.closed is True


def test_display_logs_simplifies_runner_noise(tmp_path: Path) -> None:
    module = load_cockpit_module()
    cockpit = module.Cockpit(
        make_stub_config(tmp_path),
        key_reader_factory=lambda: FakeKeyReader(["q", "y"]),
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
    key_reader = FakeKeyReader([None, "q", "y"])
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
