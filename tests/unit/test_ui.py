from __future__ import annotations

from dataclasses import dataclass

import pytest

from codexdeck_ui import (
    clean_terminal_text,
    RenderStatus,
    clamp_task_offset,
    detect_prompt_options,
    format_duration,
    render_frame,
    task_range_label,
    truncate,
)


@dataclass(frozen=True)
class Task:
    text: str
    done: bool = False
    id: str = "task-id"


def test_truncate_uses_stable_width() -> None:
    assert truncate("abcdef", 6) == "abcdef"
    assert truncate("abcdef", 5) == "ab..."
    assert truncate("abcdef", 2) == "ab"


def test_clean_terminal_text_strips_ansi_and_control_sequences() -> None:
    assert clean_terminal_text("\x1b[31mred\x1b[0m\rnext\x07") == "red next"


def test_render_strips_ansi_logs_before_measuring_width() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[
            "Codex output: \x1b[31m3 -\x1b[0m " + "x" * 200,
            "Codex output: \x1b[32m3 +\x1b[0m " + "y" * 200,
        ],
        status=RenderStatus(state="RUNNING", model="normal", last_run="12:00", errors=0),
        width=100,
        height=24,
    )

    lines = frame.splitlines()
    assert all(len(line) <= 100 for line in lines)
    assert "\x1b[" not in frame


def test_render_wraps_long_output_lines_without_expanding_footer() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[
            "Codex output: La première tâche non cochée est faite et cochée dans AI_TODO.md. "
            "Texte généré par le sub-agent, 30 mots exacts."
        ],
        status=RenderStatus(
            state="IDLE",
            model="normal",
            last_run="12:00",
            errors=0,
            message="All tasks are checked. Add an open task, then press l.",
        ),
        width=80,
        height=24,
        summary_lines=[
            "Target: line 7: Crée un agent et demande lui de me faire une histoire de 30 mots pour m'aider à tester.",
            "Tasks: 5 done | 0 open | 5 total | Auto: off",
            "Last run: 17:35:01 | Duration: 18s | Errors: 0",
        ],
    )

    assert "La première tâche non cochée est faite et cochée dans" in frame
    assert "AI_TODO.md. Texte généré par le sub-agent" in frame
    assert "Status: IDLE" in frame
    assert "(M)odel: normal" in frame


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


def test_render_uses_compact_brand_when_ascii_header_height_is_tight() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=21,
    )

    assert "▄█████" not in frame
    assert "⡎⠑ ⢀⡀ ⢀⣸" in frame
    assert "⠣⠔ ⠣⠜ ⠣⠼" in frame


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


def test_render_shows_action_required_panel_when_prompt_is_present() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["Codex output line"],
        status=RenderStatus(
            state="RUNNING",
            model="normal",
            last_run="12:00",
            errors=0,
            message="Codex is waiting for your answer.",
            prompt="Tu veux que je coche cette tache ?",
            prompt_can_answer=True,
        ),
        width=100,
        height=24,
    )

    assert "Action Required" in frame
    assert "Tu veux que je coche cette tache ?" in frame
    assert "Reply: 1 oui | 2 non | free answer | Enter send | Esc cancel" in frame


def test_detect_prompt_options_finds_yes_no_and_either_or_questions() -> None:
    assert detect_prompt_options("Do you want to continue? (y/n)") == ("yes", "no")
    assert detect_prompt_options("Est-ce que je continue ?") == ("oui", "non")
    assert detect_prompt_options("Ta couleur préférée est-elle le rouge ou le bleu ?") == ("rouge", "bleu")
    assert detect_prompt_options("Question ouverte sans choix précis") == ()


def test_render_shows_action_required_panel_for_completed_question() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["Codex output line"],
        status=RenderStatus(
            state="IDLE",
            model="normal",
            last_run="12:00",
            errors=0,
            message="Codex asked a question.",
            prompt="Ta couleur préférée est-elle le rouge ou le bleu ?",
        ),
        width=100,
        height=24,
    )

    assert "Action Required" in frame
    assert "Ta couleur préférée est-elle le rouge ou le bleu ?" in frame
    assert "Reply: 1 rouge | 2 bleu | free answer | Enter send | Esc cancel" in frame


def test_render_compact_mode_shows_prompt_before_keys() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=["log"],
        status=RenderStatus(
            state="RUNNING",
            model="normal",
            last_run="12:00",
            errors=0,
            message="Codex is waiting for your answer.",
            prompt="Do you want to continue? (y/n)",
            prompt_can_answer=True,
        ),
        width=79,
        height=10,
    )

    assert "Action required: Do you want to continue? (y/n)" in frame
    assert frame.index("Action required:") < frame.index("r:run")


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


def test_render_shrinks_todo_section_when_tasks_need_fewer_rows() -> None:
    frame = render_frame(
        tasks=[Task("first"), Task("second")],
        logs=[f"log line {index}" for index in range(12)],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=100,
        height=24,
    )

    lines = frame.splitlines()
    todo_title_index = next(index for index, line in enumerate(lines) if "AI_TODO.md" in line)
    output_title_index = next(index for index, line in enumerate(lines) if "Codex Output" in line)

    assert output_title_index - todo_title_index == 4
    assert "log line 11" in frame


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
    shortcuts_index = next(index for index, line in enumerate(lines) if "[r]run" in line)

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
    shortcuts_line = next(line for line in lines if "[r]run" in line)
    status_line = next(line for line in lines if "Status: IDLE" in line)
    runtime_line = next(line for line in lines if "(M)odel: normal" in line)

    assert "Up:" in status_line
    assert "Dur:" in status_line
    assert "Err:" in status_line
    assert "(M)odel: normal" in runtime_line
    assert "(F)ast: off" in runtime_line
    assert "(Pe)rm: default" in runtime_line
    assert "Aut(o): off" in runtime_line
    assert "Session:" in runtime_line
    assert "Up:" not in runtime_line
    assert "Dur:" not in runtime_line
    assert "Err:" not in runtime_line
    assert shortcuts_line.index("[r]run") < shortcuts_line.index("[o]auto")
    assert shortcuts_line.index("[o]auto") < shortcuts_line.index("[s]stop")
    assert shortcuts_line.index("[s]stop") < shortcuts_line.index("[k]skip")
    assert shortcuts_line.index("[k]skip") < shortcuts_line.index("[q]quit")
    assert shortcuts_line.index("[q]quit") < shortcuts_line.index("[e]edit")
    assert shortcuts_line.index("[e]edit") < shortcuts_line.index("[l]reload")
    assert "[e]edit" in shortcuts_line
    assert "[l]reload" in shortcuts_line
    assert "[n]new" in shortcuts_line
    assert "(a)dd" not in shortcuts_line
    assert "(m)odel" not in shortcuts_line
    assert "(f)ast" not in shortcuts_line
    assert "(p)erms" not in shortcuts_line
    assert "aut(o)" not in shortcuts_line
    assert "[\u2191\u2193]scroll" in shortcuts_line
    assert "(j/k)" not in shortcuts_line
    assert "[h]help" in shortcuts_line
    assert shortcuts_line.index("[h]help") < shortcuts_line.index("v1.2.3")
    assert "MIT" not in shortcuts_line


def test_render_footer_keeps_all_shortcuts_visible_at_80_columns() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0, version="1.2.3"),
        width=80,
        height=24,
    )

    lines = frame.splitlines()
    shortcuts_line = next(line for line in lines if "r:run" in line)

    assert all(len(line) <= 80 for line in lines)
    assert "r:run" in shortcuts_line
    assert "o:auto" in shortcuts_line
    assert "s:stop" in shortcuts_line
    assert "k:skip" in shortcuts_line
    assert "q:quit" in shortcuts_line
    assert "e:edit" in shortcuts_line
    assert "l:reload" in shortcuts_line
    assert "n:new" in shortcuts_line
    assert "scroll" in shortcuts_line
    assert "h:help" in shortcuts_line
    assert "v1.2.3" in shortcuts_line


def test_render_shows_warm_session_state() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[],
        status=RenderStatus(
            state="IDLE",
            model="normal",
            last_run="12:00",
            errors=0,
            message="OK. Codex session is warm for the next task.",
            session="warm",
        ),
        width=110,
        height=24,
    )

    assert "Codex session is warm" in frame
    assert "Session: warm" in frame


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
    assert "⡎⠑ ⢀⡀ ⢀⣸" in frame
    assert "⠣⠔ ⠣⠜ ⠣⠼" in frame
    assert "compact mode" in frame
    assert "r:run" in frame
    assert "n:new" in frame


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
    assert "s:stop" in frame


def test_render_full_help_uses_output_panel() -> None:
    frame = render_frame(
        tasks=[Task("task")],
        logs=[
            "What is this app doing? CodexDeck keeps AI_TODO.md visible.",
            "made by lyte | GitHub: https://github.com/MLyte/CodexDeck",
        ],
        status=RenderStatus(state="IDLE", model="normal", last_run="never", errors=0),
        width=120,
        height=24,
        show_help=True,
    )

    assert "Codex Output" in frame
    assert "What is this app doing?" in frame
    assert "made by lyte | GitHub: https://github.com/MLyte/CodexDeck" in frame
