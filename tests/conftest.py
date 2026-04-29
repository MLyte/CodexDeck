from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_LOG_PATH = REPO_ROOT / "logs" / "agent.log"

CODEXDECK_ENV_KEYS = (
    "CODEX_CMD",
    "CODEX_MODEL",
    "RUN_TIMEOUT_SECONDS",
    "STOP_TIMEOUT_SECONDS",
    "STATE_REFRESH_HZ",
    "MAX_LOG_LINES",
    "CODEX_TODO_PATH",
    "TODO_PATH",
    "CODEX_LOG_PATH",
    "LOG_PATH",
    "NO_COLOR",
    "FORCE_COLOR",
)


@dataclass(frozen=True)
class CodexDeckWorkspace:
    root: Path
    todo_path: Path
    log_path: Path


@pytest.fixture(autouse=True)
def isolated_codexdeck_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep tests away from user env and the repository log file."""

    before = REAL_LOG_PATH.read_bytes() if REAL_LOG_PATH.exists() else None

    for key in CODEXDECK_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")

    isolated_root = tmp_path / "codexdeck-env"
    isolated_root.mkdir()
    monkeypatch.setenv("CODEX_TODO_PATH", str(isolated_root / "AI_TODO.md"))
    monkeypatch.setenv("CODEX_LOG_PATH", str(isolated_root / "logs" / "agent.log"))

    yield

    after = REAL_LOG_PATH.read_bytes() if REAL_LOG_PATH.exists() else None
    assert after == before, "tests must not write to the repository logs/agent.log"


@pytest.fixture
def codexdeck_workspace(tmp_path: Path) -> CodexDeckWorkspace:
    root = tmp_path / "workspace"
    todo_path = root / "AI_TODO.md"
    log_path = root / "logs" / "agent.log"
    root.mkdir()
    todo_path.write_text("# Test TODO\n- [ ] Run stub\n", encoding="utf-8")
    return CodexDeckWorkspace(root=root, todo_path=todo_path, log_path=log_path)
