from __future__ import annotations

from dataclasses import dataclass

import pytest

from codexdeck_ui import RenderStatus, clamp_task_offset, format_duration, render_frame, task_range_label, truncate


@dataclass(frozen=True)
class Task:
    text: str
    done: bool = False
    id: str = "task-id"


def test_truncate_uses_stable_width() -> None:
    assert truncate("abcdef", 6) == "abcdef"
    assert truncate("abcdef", 5) == "ab..."
    assert truncate("abcdef", 2) == "ab"


def test_format_duration_is_compact() -> None:
    assert format_duration(None) == "-"
    assert format_duration(7.9) == "7s"
    assert format_duration(61) == "1m01s"
    assert format_duration(3661) == "1h01m"


def test_task_offset_helpers_clamp_and_label_visible_range() -> None:
    assert clamp_task_offset(10, 4, -5) == 0
    assert clamp_task_offset(10, 4, 99) == 6
    assert task_range_label(10, 4, 3) == "AI_TODO.md 4-7/10"
    assert task_range_label(0, 4, 3) == "AI_TODO.md 0/0"


@pytest.mark.parametrize(("width", "height"), [(60, 12), (80, 24), (100, 30), (120, 40)])
def test_render_never_exceeds_requested_width(width: int, height: int) -> None:
    frame = render_frame(
        tasks=[Task("a very long TODO line that must be truncated")],
        logs=["a very long log line that must also be truncated"],
        status=RenderStatus(
            state="RUNNING",
            model="normal",
            last_run="12:00",
            errors=0,
            uptime_seconds=3,
            duration_seconds=3,
        ),
        width=width,
        height=height,
    )

    lines = frame.splitlines()
    assert len(lines) == height
    assert all(len(line) <= width for line in lines)
    assert "RUNNING" in frame
    assert "Up:" in frame


def test_render_supports_ascii_borders() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["log"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=80,
        height=20,
        ascii_borders=True,
    )

    assert frame.splitlines()[0].startswith("+")
    assert "\u250c" not in frame


def test_render_status_message_is_visible() -> None:
    frame = render_frame(
        tasks=[],
        logs=[],
        status=RenderStatus(
            state="IDLE",
            model="normal",
            last_run="12:00",
            errors=0,
            message="Last run completed successfully.",
        ),
        width=100,
        height=20,
    )

    assert "Last run completed successfully." in frame


def test_render_empty_task_panel_hint_when_no_tasks() -> None:
    frame = render_frame(
        tasks=[],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=20,
        task_panel_hint=["No AI_TODO.md", "n create a starter file"],
    )

    assert "No AI_TODO.md" in frame
    assert "n create a starter file" in frame


def test_render_prioritizes_todo_column_width() -> None:
    frame = render_frame(
        tasks=[Task("Map the user journey before starting Codex")],
        logs=["log"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=20,
    )

    assert "Map the user journey before starting Codex" in frame


def test_render_task_offset_shows_scrolled_slice() -> None:
    frame = render_frame(
        tasks=[Task(f"task {index}") for index in range(25)],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=80,
        height=20,
        task_offset=3,
    )

    assert "AI_TODO.md 4-18/25" in frame
    assert "task 0" not in frame
    assert "task 3" in frame


def test_render_marks_active_task() -> None:
    frame = render_frame(
        tasks=[Task("first task", id="first"), Task("second task", id="second")],
        logs=[],
        status=RenderStatus(state="RUNNING", model="normal", last_run="12:00", errors=0),
        width=80,
        height=20,
        active_task_id="second",
    )

    assert ">[ ] second task" in frame
    assert " [ ] first task" in frame


def test_render_uses_compact_mode_for_small_terminal() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["log"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=79,
        height=10,
    )

    lines = frame.splitlines()
    assert len(lines) == 10
    assert all(len(line) == 79 for line in lines)
    assert "compact mode" in frame
    assert "r run" in frame


def test_render_compact_help_is_non_blocking_text() -> None:
    frame = render_frame(
        tasks=[],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=50,
        height=8,
        show_help=True,
    )

    assert "Help" in frame
    assert "h/? toggle" in frame
