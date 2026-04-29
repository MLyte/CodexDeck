from __future__ import annotations

import importlib.util
import os
import site
import subprocess
import sys
from pathlib import Path
import venv

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ENV_KEYS = (
    "CODEX_TODO_PATH",
    "TODO_PATH",
    "CODEX_LOG_PATH",
    "LOG_PATH",
    "CODEX_USER_LOG_PATH",
    "USER_LOG_PATH",
)


def test_python_m_entrypoint_prints_config(codexdeck_workspace) -> None:
    env = os.environ.copy()
    env.update(
        {
            "CODEX_TODO_PATH": str(codexdeck_workspace.todo_path),
            "CODEX_LOG_PATH": str(codexdeck_workspace.log_path),
            "CODEX_USER_LOG_PATH": str(codexdeck_workspace.root / "logs" / "user.log"),
            "CODEX_CMD": "codex {todo}",
            "CODEX_MODEL": "normal",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "codexdeck", "--print-config"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert f"todo_path: {codexdeck_workspace.todo_path}" in result.stdout
    assert f"log_path: {codexdeck_workspace.log_path}" in result.stdout
    assert f"user_log_path: {codexdeck_workspace.root / 'logs' / 'user.log'}" in result.stdout
    assert "codex_cmd: codex {todo}" in result.stdout


def test_installed_console_script_uses_launch_cwd(tmp_path) -> None:
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("setuptools is required for the offline editable-install acceptance test")

    venv_dir = tmp_path / "venv"
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    venv.EnvBuilder(with_pip=True).create(venv_dir)

    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    python_exe = venv_dir / scripts_dir / ("python.exe" if os.name == "nt" else "python")
    codexdeck_exe = venv_dir / scripts_dir / ("codexdeck.exe" if os.name == "nt" else "codexdeck")

    install = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "-e",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(site.getsitepackages()),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert install.returncode == 0, install.stderr

    launch_env = os.environ.copy()
    for key in CONFIG_ENV_KEYS:
        launch_env.pop(key, None)
    launch_env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "CODEX_CMD": "codex {todo}",
        }
    )

    result = subprocess.run(
        [str(codexdeck_exe), "--print-config"],
        cwd=launch_dir,
        env=launch_env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert f"todo_path: {launch_dir / 'AI_TODO.md'}" in result.stdout
    assert f"log_path: {launch_dir / 'logs' / 'agent.log'}" in result.stdout
    assert f"user_log_path: {launch_dir / 'logs' / 'user.log'}" in result.stdout
