import logging
from pathlib import Path

import pytest

from codexdeck_core import ConfigError, ErrorCode, parse_todo_file


def test_parse_todo_file_supports_markers_indents_and_sections(tmp_path: Path) -> None:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text(
        "\n".join(
            [
                "# Backlog",
                "intro text",
                "## Core",
                "- [ ] first task",
                "  * [x] done task",
                "    - [X] uppercase done",
                "## UI",
                "\t- [ ] tab indented",
            ]
        ),
        encoding="utf-8",
    )

    tasks = parse_todo_file(todo)

    assert [task.text for task in tasks] == [
        "first task",
        "done task",
        "uppercase done",
        "tab indented",
    ]
    assert [task.done for task in tasks] == [False, True, True, False]
    assert [task.section for task in tasks] == ["Core", "Core", "Core", "UI"]
    assert tasks[0].line == 4
    assert tasks[0].raw == "- [ ] first task"
    assert tasks[0].id


def test_parse_todo_file_logs_invalid_task_like_lines_without_crashing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text(
        "\n".join(
            [
                "- [] missing space",
                "- [q] wrong marker",
                "- [ ] valid",
                "plain text is ignored",
            ]
        ),
        encoding="utf-8",
    )
    logger = logging.getLogger("codexdeck.tests")

    with caplog.at_level(logging.WARNING, logger="codexdeck.tests"):
        tasks = parse_todo_file(todo, logger=logger)

    assert [task.text for task in tasks] == ["valid"]
    assert "Ignoring invalid TODO line 1" in caplog.text
    assert "Ignoring invalid TODO line 2" in caplog.text
    assert "plain text is ignored" not in caplog.text


def test_parse_todo_file_missing_file_raises_normalized_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        parse_todo_file(tmp_path / "missing.md")

    assert exc_info.value.error_code is ErrorCode.TODO_NOT_FOUND
