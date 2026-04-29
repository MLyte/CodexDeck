import sys

import pytest

import codexdeck


def test_main_exits_cleanly_on_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["codexdeck"])

    def raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(codexdeck.runpy, "run_path", raise_keyboard_interrupt)

    with pytest.raises(SystemExit) as excinfo:
        codexdeck.main()

    assert excinfo.value.code == 130
