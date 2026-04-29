from pathlib import Path

import pytest

from codexdeck_core import CockpitConfig, ConfigError, ErrorCode


def test_config_from_env_uses_defaults_and_resolves_paths(tmp_path: Path) -> None:
    config = CockpitConfig.from_env({}, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "AI_TODO.md"
    assert config.log_path == tmp_path / "logs" / "agent.log"
    assert config.user_log_path == tmp_path / "logs" / "user.log"
    assert config.codex_cmd == "codex {todo}"
    assert config.model == "gpt-5.5"
    assert config.models == (
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
    )
    assert config.fast_model == "gpt-5.3-codex-spark"
    assert config.permission == "default"
    assert config.permissions == ("default", "read-only", "workspace-write", "danger-full-access")
    assert config.run_timeout == 3600.0
    assert config.refresh_hz == 8.0
    assert config.max_log_lines == 5000


def test_config_from_env_reads_supported_values(tmp_path: Path) -> None:
    env = {
        "CODEX_CMD": "python stub.py {todo}",
        "CODEX_MODEL": "gpt-test",
        "CODEX_MODELS": "gpt-test,gpt-alt",
        "CODEX_FAST_MODEL": "gpt-fast",
        "CODEX_PERMISSION": "workspace-write",
        "CODEX_PERMISSIONS": "default,workspace-write",
        "RUN_TIMEOUT_SECONDS": "12.5",
        "STOP_TIMEOUT_SECONDS": "2",
        "STATE_REFRESH_HZ": "20",
        "MAX_LOG_LINES": "42",
        "CODEX_TODO_PATH": "todo.md",
        "CODEX_LOG_PATH": "out/agent.log",
        "CODEX_USER_LOG_PATH": "out/user.log",
    }

    config = CockpitConfig.from_env(env, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "todo.md"
    assert config.log_path == tmp_path / "out" / "agent.log"
    assert config.user_log_path == tmp_path / "out" / "user.log"
    assert config.codex_cmd == "python stub.py {todo}"
    assert config.model == "gpt-test"
    assert config.models == ("gpt-test", "gpt-alt")
    assert config.fast_model == "gpt-fast"
    assert config.permission == "workspace-write"
    assert config.permissions == ("default", "workspace-write")
    assert config.run_timeout == 12.5
    assert config.stop_timeout == 2.0
    assert config.refresh_hz == 20.0
    assert config.max_log_lines == 42


def test_config_absent_file_uses_defaults(tmp_path: Path) -> None:
    config = CockpitConfig.from_env({}, base_dir=tmp_path)

    assert config.codex_cmd == "codex {todo}"
    assert config.todo_path == tmp_path / "AI_TODO.md"


def test_config_file_reads_supported_values(tmp_path: Path) -> None:
    (tmp_path / "codexdeck.conf").write_text(
        "\n".join(
            [
                "# CodexDeck local config",
                "CODEX_CMD = python tests/stubs/codex_stub.py --mode success {todo}",
                "CODEX_MODEL=gpt-conf",
                "CODEX_MODELS=gpt-conf,gpt-alt",
                "CODEX_FAST_MODEL=gpt-fast",
                "CODEX_PERMISSION=read-only",
                "CODEX_PERMISSIONS=default,read-only",
                "RUN_TIMEOUT_SECONDS=30",
                "STOP_TIMEOUT_SECONDS=3",
                "STATE_REFRESH_HZ=12",
                "MAX_LOG_LINES=77",
                "CODEX_TODO_PATH=config-todo.md",
                "CODEX_LOG_PATH=config-logs/agent.log",
                "CODEX_USER_LOG_PATH=config-logs/user.log",
            ]
        ),
        encoding="utf-8",
    )

    config = CockpitConfig.from_env({}, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "config-todo.md"
    assert config.log_path == tmp_path / "config-logs" / "agent.log"
    assert config.user_log_path == tmp_path / "config-logs" / "user.log"
    assert config.codex_cmd == "python tests/stubs/codex_stub.py --mode success {todo}"
    assert config.model == "gpt-conf"
    assert config.models == ("gpt-conf", "gpt-alt")
    assert config.fast_model == "gpt-fast"
    assert config.permission == "read-only"
    assert config.permissions == ("default", "read-only")
    assert config.run_timeout == 30.0
    assert config.stop_timeout == 3.0
    assert config.refresh_hz == 12.0
    assert config.max_log_lines == 77


def test_env_values_override_config_file(tmp_path: Path) -> None:
    (tmp_path / "codexdeck.conf").write_text(
        "\n".join(
            [
                "CODEX_CMD=from-file {todo}",
                "CODEX_MODEL=file-model",
                "MAX_LOG_LINES=10",
                "CODEX_TODO_PATH=file.md",
            ]
        ),
        encoding="utf-8",
    )

    config = CockpitConfig.from_env(
        {
            "CODEX_CMD": "from-env {todo}",
            "CODEX_MODEL": "env-model",
            "CODEX_MODELS": "env-model,env-fast",
            "MAX_LOG_LINES": "20",
            "CODEX_TODO_PATH": "env.md",
        },
        base_dir=tmp_path,
    )

    assert config.codex_cmd == "from-env {todo}"
    assert config.model == "env-model"
    assert config.models == ("env-model", "env-fast")
    assert config.max_log_lines == 20
    assert config.todo_path == tmp_path / "env.md"


def test_configured_current_model_and_permission_are_kept_in_choices(tmp_path: Path) -> None:
    config = CockpitConfig.from_env(
        {
            "CODEX_MODEL": "current-model",
            "CODEX_MODELS": "other-model",
            "CODEX_PERMISSION": "current-permission",
            "CODEX_PERMISSIONS": "other-permission",
        },
        base_dir=tmp_path,
    )

    assert config.models == ("other-model", "current-model")
    assert config.permissions == ("other-permission", "current-permission")


def test_config_path_can_be_selected_from_env(tmp_path: Path) -> None:
    custom = tmp_path / "custom.conf"
    custom.write_text("CODEX_MODEL=custom-model\n", encoding="utf-8")

    config = CockpitConfig.from_env({"CODEX_CONFIG_PATH": str(custom)}, base_dir=tmp_path)

    assert config.model == "custom-model"


def test_config_file_rejects_invalid_lines(tmp_path: Path) -> None:
    (tmp_path / "codexdeck.conf").write_text("not-a-setting\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        CockpitConfig.from_env({}, base_dir=tmp_path)

    assert exc_info.value.error_code is ErrorCode.INVALID_CONFIG
    assert "expected KEY=VALUE" in exc_info.value.message


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("RUN_TIMEOUT_SECONDS", "0"),
        ("STOP_TIMEOUT_SECONDS", "-1"),
        ("STATE_REFRESH_HZ", "0"),
        ("MAX_LOG_LINES", "0"),
        ("CODEX_CMD", " "),
        ("CODEX_MODEL", ""),
        ("CODEX_MODELS", ","),
        ("CODEX_FAST_MODEL", ""),
        ("CODEX_PERMISSION", ""),
        ("CODEX_PERMISSIONS", ","),
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
