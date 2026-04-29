from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_python_m_entrypoint_prints_config(codexdeck_workspace) -> None:
    env = os.environ.copy()
    env.update(
        {
            "CODEX_TODO_PATH": str(codexdeck_workspace.todo_path),
            "CODEX_LOG_PATH": str(codexdeck_workspace.log_path),
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
    assert "codex_cmd: codex {todo}" in result.stdout
