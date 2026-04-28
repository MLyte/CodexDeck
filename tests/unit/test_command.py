from pathlib import Path

import pytest

from codexdeck_core import CockpitConfig, CommandError, ErrorCode, build_command


def test_build_command_interpolates_todo_placeholders(tmp_path: Path) -> None:
    todo = _todo(tmp_path)

    assert build_command("codex run {todo}", todo) == ["codex", "run", todo.resolve().as_posix()]
    assert build_command("codex run $TODO", todo) == ["codex", "run", todo.resolve().as_posix()]
    assert build_command("codex run %TODO%", todo) == ["codex", "run", todo.resolve().as_posix()]


def test_build_command_supports_quoted_arguments_with_spaces(tmp_path: Path) -> None:
    todo = _todo(tmp_path)

    command = build_command('python -m stub --label "hello world" "{todo}"', todo)

    assert command == ["python", "-m", "stub", "--label", "hello world", todo.resolve().as_posix()]


def test_build_command_accepts_config_object(tmp_path: Path) -> None:
    todo = _todo(tmp_path)
    config = CockpitConfig(todo_path=todo, log_path=tmp_path / "agent.log", codex_cmd="codex {todo}")

    assert build_command(config) == ["codex", todo.resolve().as_posix()]


def test_build_command_rejects_empty_command(tmp_path: Path) -> None:
    todo = _todo(tmp_path)

    with pytest.raises(CommandError) as exc_info:
        build_command(" ", todo)

    assert exc_info.value.error_code is ErrorCode.INVALID_COMMAND


def test_build_command_rejects_missing_todo_path_argument() -> None:
    with pytest.raises(CommandError) as exc_info:
        build_command("codex {todo}")

    assert exc_info.value.error_code is ErrorCode.TODO_NOT_FOUND


def test_build_command_rejects_nonexistent_todo_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError) as exc_info:
        build_command("codex {todo}", tmp_path / "missing.md")

    assert exc_info.value.error_code is ErrorCode.TODO_NOT_FOUND


def test_build_command_can_require_todo_placeholder(tmp_path: Path) -> None:
    todo = _todo(tmp_path)

    with pytest.raises(CommandError) as exc_info:
        build_command("codex run", todo, require_todo_placeholder=True)

    assert exc_info.value.error_code is ErrorCode.INVALID_COMMAND


def _todo(tmp_path: Path) -> Path:
    todo = tmp_path / "AI_TODO.md"
    todo.write_text("- [ ] task\n", encoding="utf-8")
    return todo
