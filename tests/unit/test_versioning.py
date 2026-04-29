from __future__ import annotations

import importlib.metadata

import codexdeck_version


def test_resolve_version_prefers_package_metadata(monkeypatch) -> None:
    codexdeck_version.resolve_version.cache_clear()

    def fake_version(name: str) -> str:
        if name == "codexdeck":
            return "1.4.2"
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    monkeypatch.setattr(codexdeck_version, "_resolve_git_version", lambda _root: "")

    assert codexdeck_version.resolve_version() == "1.4.2"


def test_resolve_version_falls_back_to_git_describe(monkeypatch) -> None:
    codexdeck_version.resolve_version.cache_clear()

    def fake_version(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    monkeypatch.setattr(codexdeck_version, "_resolve_git_version", lambda _root: "1.4.2+3.gabc123")

    assert codexdeck_version.resolve_version() == "1.4.2+3.gabc123"


def test_resolve_version_uses_default_when_nothing_available(monkeypatch) -> None:
    codexdeck_version.resolve_version.cache_clear()

    def fake_version(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    monkeypatch.setattr(codexdeck_version, "_resolve_git_version", lambda _root: "")

    assert codexdeck_version.resolve_version() == "0.0.0"
