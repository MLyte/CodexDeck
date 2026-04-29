from __future__ import annotations

import pytest

from codexdeck import __version__
from codexdeck import app, cli


def test_cli_prints_version(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out == f"codexdeck {__version__}\n"


def test_cli_prints_help(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])

    assert excinfo.value.code == 0
    assert "usage: codexdeck" in capsys.readouterr().out


def test_app_main_exits_cleanly_on_keyboard_interrupt(monkeypatch, capsys, codexdeck_workspace):
    monkeypatch.chdir(codexdeck_workspace.root)
    monkeypatch.setenv("CODEX_TODO_PATH", str(codexdeck_workspace.todo_path))

    def raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(app.Cockpit, "loop", raise_keyboard_interrupt)

    with pytest.raises(SystemExit) as excinfo:
        app.main()

    assert excinfo.value.code == 0
    assert capsys.readouterr().out == "\nCodexDeck stopped cleanly.\n"

