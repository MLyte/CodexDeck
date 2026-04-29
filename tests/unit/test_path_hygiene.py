from __future__ import annotations

from pathlib import Path

from codexdeck_core import CockpitConfig


def test_default_paths_are_project_relative_and_utf8_safe(tmp_path: Path) -> None:
    config = CockpitConfig.from_env({}, base_dir=tmp_path)

    assert config.todo_path == tmp_path / "AI_TODO.md"
    assert config.log_path == tmp_path / "logs" / "agent.log"

    config.todo_path.write_text("- [ ] tâche accentuée\n", encoding="utf-8")
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    config.log_path.write_text("ligne accentuée\n", encoding="utf-8")

    assert "tâche" in config.todo_path.read_text(encoding="utf-8")
    assert "ligne" in config.log_path.read_text(encoding="utf-8")
