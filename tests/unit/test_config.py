from pathlib import Path

import pytest

from codexdeck_core import CockpitConfig, ConfigError, ErrorCode


def test_config_from_env_uses_defaults_and_resolves_paths(tmp_path: Path) -> None:
    config = CockpitConfig.from_env({}, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "AI_TODO.md"
    assert config.log_path == tmp_path / "logs" / "agent.log"
    assert config.codex_cmd == "codex {todo}"
    assert config.model == "normal"
    assert config.run_timeout == 3600.0
    assert config.refresh_hz == 8.0
    assert config.max_log_lines == 5000


def test_config_from_env_reads_supported_values(tmp_path: Path) -> None:
    env = {
        "CODEX_CMD": "python stub.py {todo}",
        "CODEX_MODEL": "gpt-test",
        "RUN_TIMEOUT_SECONDS": "12.5",
        "STOP_TIMEOUT_SECONDS": "2",
        "STATE_REFRESH_HZ": "20",
        "MAX_LOG_LINES": "42",
        "CODEX_TODO_PATH": "todo.md",
        "CODEX_LOG_PATH": "out/agent.log",
    }

    config = CockpitConfig.from_env(env, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "todo.md"
    assert config.log_path == tmp_path / "out" / "agent.log"
    assert config.codex_cmd == "python stub.py {todo}"
    assert config.model == "gpt-test"
    assert config.run_timeout == 12.5
    assert config.stop_timeout == 2.0
    assert config.refresh_hz == 20.0
    assert config.max_log_lines == 42


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("RUN_TIMEOUT_SECONDS", "0"),
        ("STOP_TIMEOUT_SECONDS", "-1"),
        ("STATE_REFRESH_HZ", "0"),
        ("MAX_LOG_LINES", "0"),
        ("CODEX_CMD", " "),
        ("CODEX_MODEL", ""),
    ],
)
def test_config_rejects_invalid_values(tmp_path: Path, key: str, value: str) -> None:
    with pytest.raises(ConfigError) as exc_info:
        CockpitConfig.from_env({key: value}, base_dir=tmp_path)

    assert exc_info.value.error_code is ErrorCode.INVALID_CONFIG


def test_config_rejects_unparseable_numbers(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        CockpitConfig.from_env({"RUN_TIMEOUT_SECONDS": "slow"}, base_dir=tmp_path)

    assert exc_info.value.error_code is ErrorCode.INVALID_CONFIG
