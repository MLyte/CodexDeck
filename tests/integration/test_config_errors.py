from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_rejects_invalid_config_with_clear_message() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codexdeck"],
        env={"CODEX_CMD": " ", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Config error [INVALID_CONFIG]" in result.stderr
    assert "CODEX_CMD must not be empty" in result.stderr
