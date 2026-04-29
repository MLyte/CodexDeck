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
    assert "██████" not in frame


def test_render_shows_codexdeck_ascii_header_when_space_allows() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=30,
    )

    lines = frame.splitlines()
    assert len(lines) == 30
    assert "▄█████  ▄▄▄  ▄▄▄▄" in frame
    assert "AI_TODO.md 1-1/1" in frame


def test_render_hides_codexdeck_ascii_header_when_height_is_tight() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=21,
    )

    assert "▄█████" not in frame


def test_render_keeps_codexdeck_ascii_header_with_help_when_space_allows() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[
            "Help: CodexDeck keeps AI_TODO.md visible, runs one Codex process, and streams output.",
            "made by lyte | GitHub: https://github.com/MLyte/CodexDeck",
        ],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=120,
        height=36,
        show_help=True,
    )

    assert "▄█████  ▄▄▄  ▄▄▄▄" in frame
    assert "Codex Output" in frame
    assert "Help: CodexDeck keeps AI_TODO.md visible" in frame
    assert "made by lyte | GitHub: https://github.com/MLyte/CodexDeck" in frame


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
        task_panel_hint=["No AI_TODO.md", "n add the first task", "Ctrl-S saves it"],
    )

    assert "No AI_TODO.md" in frame
    assert "n add the first task" in frame
    assert "Ctrl-S saves it" in frame


def test_render_prioritizes_todo_column_width() -> None:
    frame = render_frame(
        tasks=[Task("Map the user journey before starting Codex")],
        logs=["log"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=20,
    )

    assert "Map the user journey before starting Codex" in frame


def test_render_wraps_very_long_task_in_full_width_todo_section() -> None:
    task = (
        "Check that a very long task remains readable across the full-width TODO section without being cut too "
        "aggressively in a normal 100-column terminal."
    )

    frame = render_frame(
        tasks=[Task(task)],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=20,
    )

    lines = frame.splitlines()
    assert len(lines) == 20
    assert all(len(line) <= 100 for line in lines)
    assert "Check that a very long task remains readable across the full-width TODO section" in frame
    assert "aggressively in a normal 100-column terminal." in frame
    assert "..." not in "\n".join(lines[2:5])


def test_render_task_offset_shows_scrolled_slice() -> None:
    frame = render_frame(
        tasks=[Task(f"task {index}") for index in range(25)],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=80,
        height=20,
        task_offset=3,
    )

    assert "AI_TODO.md 4-7/25" in frame
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


def test_render_uses_horizontal_sections_with_summary() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["log line"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=24,
        summary_lines=["Target: line 1: task", "Tasks: 0 done | 1 open | 1 total"],
    )

    assert "AI_TODO.md 1-1/1" in frame
    assert "Codex Output" in frame
    assert "Task Summary" in frame
    assert "Target: line 1: task" in frame


def test_render_horizontal_layout_orders_todo_output_summary_and_status() -> None:
    frame = render_frame(
        tasks=[Task("first task")],
        logs=["codex output line"],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=24,
        summary_lines=["Target: line 1: first task"],
    )

    lines = frame.splitlines()
    todo_index = next(index for index, line in enumerate(lines) if "AI_TODO.md 1-1/1" in line)
    output_index = next(index for index, line in enumerate(lines) if "Codex Output" in line)
    summary_index = next(index for index, line in enumerate(lines) if "Task Summary" in line)
    status_index = next(index for index, line in enumerate(lines) if "Status: IDLE" in line)
    runtime_index = next(index for index, line in enumerate(lines) if "(M)odel: normal" in line)
    shortcuts_index = next(index for index, line in enumerate(lines) if "Keys: (r)un CodexDeck" in line)

    assert todo_index < output_index < summary_index < status_index
    assert runtime_index == status_index + 1
    assert shortcuts_index == runtime_index + 1
    assert shortcuts_index == len(lines) - 2


def test_render_footer_lists_shortcuts_by_importance() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0, version="1.2.3"),
        width=140,
        height=24,
    )

    lines = frame.splitlines()
    shortcuts_line = next(line for line in lines if "Keys: (r)un CodexDeck" in line)
    status_line = next(line for line in lines if "Status: IDLE" in line)
    runtime_line = next(line for line in lines if "(M)odel: normal" in line)

    assert "Up:" in status_line
    assert "Dur:" in status_line
    assert "Err:" in status_line
    assert "(M)odel: normal" in runtime_line
    assert "(F)ast: off" in runtime_line
    assert "(Pe)rm: default" in runtime_line
    assert "Aut(o): off" in runtime_line
    assert "Up:" not in runtime_line
    assert "Dur:" not in runtime_line
    assert "Err:" not in runtime_line
    assert shortcuts_line.index("(r)un CodexDeck") < shortcuts_line.index("(s)top")
    assert shortcuts_line.index("(s)top") < shortcuts_line.index("(q)uit")
    assert shortcuts_line.index("(q)uit") < shortcuts_line.index("(e)dit")
    assert shortcuts_line.index("(e)dit") < shortcuts_line.index("lo(g)")
    assert shortcuts_line.index("lo(g)") < shortcuts_line.index("re(l)oad")
    assert "(e)dit" in shortcuts_line
    assert "lo(g)" in shortcuts_line
    assert "re(l)oad" in shortcuts_line
    assert "(n)ew" in shortcuts_line
    assert "(a)dd" not in shortcuts_line
    assert "(m)odel" not in shortcuts_line
    assert "(f)ast" not in shortcuts_line
    assert "(p)erms" not in shortcuts_line
    assert "aut(o)" not in shortcuts_line
    assert "\u2191\u2193 scroll" in shortcuts_line
    assert "(j/k)" not in shortcuts_line
    assert "(h)elp" in shortcuts_line
    assert shortcuts_line.index("(h)elp") < shortcuts_line.index("v1.2.3")
    assert "MIT" in shortcuts_line


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
    assert "(r)un" in frame
    assert "(n)ew" in frame


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
    assert "(s)top" in frame


def test_render_full_help_uses_output_panel() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[
            "What is this app doing? CodexDeck keeps AI_TODO.md visible.",
            "made by lyte | GitHub: https://github.com/MLyte/CodexDeck",
        ],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0, version="1.2.3"),
        width=120,
        height=24,
        show_help=True,
    )

    assert "Codex Output" in frame
    assert "What is this app doing?" in frame
    assert "made by lyte | GitHub: https://github.com/MLyte/CodexDeck" in frame
