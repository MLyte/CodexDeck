"""Testable core primitives for CodexDeck.

This module intentionally avoids terminal, subprocess and shell side effects.
The TUI can import these pieces without needing to parse markdown or environment
variables directly.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional


SUBPROCESS_SHELL = False
DEFAULT_MODELS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
)
DEFAULT_FAST_MODEL = "gpt-5.3-codex-spark"
DEFAULT_CODEX_CMD = (
    'codex exec --model {model} --skip-git-repo-check '
    '"Read {todo}. Work on the first unchecked task only."'
)


class ErrorCode(str, Enum):
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    PROCESS_ALREADY_RUNNING = "PROCESS_ALREADY_RUNNING"
    PROCESS_NOT_RUNNING = "PROCESS_NOT_RUNNING"
    RUN_TIMEOUT = "RUN_TIMEOUT"
    TODO_NOT_FOUND = "TODO_NOT_FOUND"


class CodexDeckError(Exception):
    """Base exception carrying a stable error code and a short message."""

    def __init__(self, error_code: ErrorCode, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.cause = cause


class ConfigError(CodexDeckError):
    pass


class CommandError(CodexDeckError):
    pass


class StateTransitionError(CodexDeckError):
    pass


@dataclass(frozen=True)
class CockpitConfig:
    todo_path: Path
    log_path: Path
    user_log_path: Path
    codex_cmd: str = DEFAULT_CODEX_CMD
    model: str = DEFAULT_MODELS[0]
    models: tuple[str, ...] = DEFAULT_MODELS
    fast_model: str = DEFAULT_FAST_MODEL
    permission: str = "default"
    permissions: tuple[str, ...] = ("default", "read-only", "workspace-write", "danger-full-access")
    run_timeout: float = 3600.0
    stop_timeout: float = 5.0
    refresh_hz: float = 8.0
    max_log_lines: int = 5000

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        base_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> "CockpitConfig":
        root = Path.cwd() if base_dir is None else Path(base_dir)
        env_values = os.environ if env is None else env
        resolved_config_path = config_path or env_values.get("CODEX_CONFIG_PATH")
        file_values = _read_config_file(_resolve_config_path(resolved_config_path, root))
        source = {**file_values, **env_values}
        todo_path = _resolve_path(
            source.get("CODEX_TODO_PATH") or source.get("TODO_PATH") or "AI_TODO.md",
            root,
        )
        log_path = _resolve_path(
            source.get("CODEX_LOG_PATH") or source.get("LOG_PATH") or str(Path("logs") / "agent.log"),
            root,
        )
        user_log_path = _resolve_path(
            source.get("CODEX_USER_LOG_PATH") or source.get("USER_LOG_PATH") or str(Path("logs") / "user.log"),
            root,
        )
        model = source.get("CODEX_MODEL", DEFAULT_MODELS[0])
        fast_model = source.get("CODEX_FAST_MODEL", DEFAULT_FAST_MODEL)
        permission = source.get("CODEX_PERMISSION", "default")
        config = cls(
            todo_path=todo_path,
            log_path=log_path,
            user_log_path=user_log_path,
            codex_cmd=source.get("CODEX_CMD", DEFAULT_CODEX_CMD),
            model=model,
            models=_csv_values(source.get("CODEX_MODELS"), defaults=DEFAULT_MODELS, required=(model,)),
            fast_model=fast_model,
            permission=permission,
            permissions=_csv_values(
                source.get("CODEX_PERMISSIONS"),
                defaults=(permission, "read-only", "workspace-write", "danger-full-access"),
                required=(permission,),
            ),
            run_timeout=_float_env(source, "RUN_TIMEOUT_SECONDS", 3600.0),
            stop_timeout=_float_env(source, "STOP_TIMEOUT_SECONDS", 5.0),
            refresh_hz=_float_env(source, "STATE_REFRESH_HZ", 8.0),
            max_log_lines=_int_env(source, "MAX_LOG_LINES", 5000),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not str(self.codex_cmd).strip():
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_CMD must not be empty")
        if not str(self.model).strip():
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_MODEL must not be empty")
        if not self.models:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_MODELS must include at least one model")
        if any(not str(model).strip() for model in self.models):
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_MODELS must not include empty values")
        if not str(self.fast_model).strip():
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_FAST_MODEL must not be empty")
        if not str(self.permission).strip():
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_PERMISSION must not be empty")
        if not self.permissions:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_PERMISSIONS must include at least one permission")
        if any(not str(permission).strip() for permission in self.permissions):
            raise ConfigError(ErrorCode.INVALID_CONFIG, "CODEX_PERMISSIONS must not include empty values")
        if self.run_timeout <= 0:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "RUN_TIMEOUT_SECONDS must be greater than 0")
        if self.stop_timeout <= 0:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "STOP_TIMEOUT_SECONDS must be greater than 0")
        if self.refresh_hz <= 0:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "STATE_REFRESH_HZ must be greater than 0")
        if self.max_log_lines <= 0:
            raise ConfigError(ErrorCode.INVALID_CONFIG, "MAX_LOG_LINES must be greater than 0")


@dataclass(frozen=True)
class TodoTask:
    id: str
    text: str
    done: bool
    line: int
    section: str | None
    raw: str


def parse_todo_file(path: Path | str, logger: logging.Logger | None = None) -> list[TodoTask]:
    todo_path = Path(path)
    if not todo_path.exists():
        raise ConfigError(ErrorCode.TODO_NOT_FOUND, f"TODO file not found: {todo_path}")

    current_section: str | None = None
    tasks: list[TodoTask] = []
    for line_number, raw in enumerate(todo_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            current_section = stripped.lstrip("#").strip() or None
            continue

        task = _parse_task_line(raw, line_number, current_section)
        if task is not None:
            tasks.append(task)
            continue

        if _looks_like_task(raw):
            _warn_invalid_line(logger, line_number, raw)

    return tasks


class RunState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.IDLE: frozenset({RunState.STARTING}),
    RunState.STARTING: frozenset({RunState.RUNNING, RunState.ERROR, RunState.STOPPING}),
    RunState.RUNNING: frozenset({RunState.STOPPING, RunState.ERROR}),
    RunState.STOPPING: frozenset({RunState.IDLE, RunState.ERROR}),
    RunState.ERROR: frozenset({RunState.IDLE, RunState.STARTING}),
}


@dataclass
class RunContext:
    run_id: str | None = None
    pid: int | None = None
    start_ts: float | None = None
    last_error: CodexDeckError | None = None


@dataclass
class StateMachine:
    state: RunState = RunState.IDLE
    context: RunContext | None = None

    def transition_to(self, next_state: RunState) -> RunState:
        if next_state not in ALLOWED_TRANSITIONS[self.state]:
            raise StateTransitionError(
                ErrorCode.INVALID_TRANSITION,
                f"Invalid transition: {self.state.value} -> {next_state.value}",
            )
        self.state = next_state
        return self.state


def build_command(
    command_or_config: str | CockpitConfig,
    todo_path: Path | str | None = None,
    *,
    require_todo_placeholder: bool = False,
) -> list[str]:
    """Return argv for subprocess execution with ``shell=False``."""

    if isinstance(command_or_config, CockpitConfig):
        raw_command = command_or_config.codex_cmd
        resolved_todo = command_or_config.todo_path if todo_path is None else Path(todo_path)
    else:
        raw_command = command_or_config
        if todo_path is None:
            raise CommandError(ErrorCode.TODO_NOT_FOUND, "todo_path is required")
        resolved_todo = Path(todo_path)

    if not str(raw_command).strip():
        raise CommandError(ErrorCode.INVALID_COMMAND, "Command must not be empty")

    placeholder_found = any(token in raw_command for token in ("{todo}", "$TODO", "%TODO%"))
    if require_todo_placeholder and not placeholder_found:
        raise CommandError(ErrorCode.INVALID_COMMAND, "Command must include a TODO placeholder")
    if not resolved_todo.exists():
        raise CommandError(ErrorCode.TODO_NOT_FOUND, f"TODO file not found: {resolved_todo}")

    todo_arg = resolved_todo.resolve().as_posix()
    interpolated = (
        raw_command.replace("{todo}", todo_arg)
        .replace("$TODO", todo_arg)
        .replace("%TODO%", todo_arg)
    )
    try:
        args = shlex.split(interpolated)
    except ValueError as exc:
        raise CommandError(ErrorCode.INVALID_COMMAND, "Command could not be parsed", exc) from exc
    if not args:
        raise CommandError(ErrorCode.INVALID_COMMAND, "Command must not be empty")
    return args


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def _resolve_config_path(config_path: Path | str | None, base_dir: Path) -> Path:
    if config_path is None:
        return base_dir / "codexdeck.conf"
    return _resolve_path(str(config_path), base_dir)


def _read_config_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(ErrorCode.INVALID_CONFIG, f"Could not read config file: {path}", exc) from exc
    for line_number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ConfigError(
                ErrorCode.INVALID_CONFIG,
                f"Invalid config line {line_number}: expected KEY=VALUE",
            )
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(
                ErrorCode.INVALID_CONFIG,
                f"Invalid config line {line_number}: key must not be empty",
            )
        values[key] = value.strip()
    return values


def _csv_values(value: str | None, *, defaults: tuple[str, ...], required: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw_values = defaults if value is None else tuple(part.strip() for part in value.split(","))
    if value is not None and not any(str(raw_value).strip() for raw_value in raw_values):
        return ()
    values: list[str] = []
    for raw_value in (*raw_values, *required):
        item = str(raw_value).strip()
        if item and item not in values:
            values.append(item)
    return tuple(values)


def _float_env(source: Mapping[str, str], key: str, default: float) -> float:
    value = source.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(ErrorCode.INVALID_CONFIG, f"{key} must be a number", exc) from exc


def _int_env(source: Mapping[str, str], key: str, default: int) -> int:
    value = source.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(ErrorCode.INVALID_CONFIG, f"{key} must be an integer", exc) from exc


def _parse_task_line(raw: str, line_number: int, section: Optional[str]) -> TodoTask | None:
    stripped = raw.lstrip()
    if not (stripped.startswith("- [") or stripped.startswith("* [")):
        return None
    if len(stripped) < 6 or stripped[3] not in {" ", "x", "X"} or stripped[4:6] != "] ":
        return None
    text = stripped[6:].strip()
    if not text:
        return None
    return TodoTask(
        id=_task_id(line_number, raw),
        text=text,
        done=stripped[3].lower() == "x",
        line=line_number,
        section=section,
        raw=raw,
    )


def _looks_like_task(raw: str) -> bool:
    stripped = raw.lstrip()
    return stripped.startswith(("- [", "* [")) or "[ ]" in stripped or "[x]" in stripped or "[X]" in stripped


def _warn_invalid_line(logger: logging.Logger | None, line_number: int, raw: str) -> None:
    if logger is not None:
        logger.warning("Ignoring invalid TODO line %s: %s", line_number, raw)


def _task_id(line_number: int, raw: str) -> str:
    digest = hashlib.sha1(f"{line_number}:{raw}".encode("utf-8")).hexdigest()
    return digest[:12]
