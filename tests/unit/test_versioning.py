from __future__ import annotations

import importlib.metadata

import pytest

import codexdeck.version as version_module


@pytest.fixture(autouse=True)
def clear_version_cache() -> None:
    version_module.resolve_version.cache_clear()
    yield
    version_module.resolve_version.cache_clear()


def test_resolve_version_prefers_installed_distribution(monkeypatch) -> None:
    def fake_version(name: str) -> str:
        if name == "codexdeck":
            return "v1.4.2"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version_module.importlib.metadata, "version", fake_version)
    monkeypatch.setattr(version_module, "_resolve_git_version", lambda root: "9.9.9")

    assert version_module.resolve_version() == "1.4.2"


def test_resolve_version_falls_back_to_git(monkeypatch) -> None:
    def fake_version(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version_module.importlib.metadata, "version", fake_version)
    monkeypatch.setattr(version_module, "_resolve_git_version", lambda root: "2.0.0+5.gabc123")

    assert version_module.resolve_version() == "2.0.0+5.gabc123"


def test_resolve_version_returns_default_when_unavailable(monkeypatch) -> None:
    def fake_version(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version_module.importlib.metadata, "version", fake_version)
    monkeypatch.setattr(version_module, "_resolve_git_version", lambda root: "")

    assert version_module.resolve_version() == "0.0.0"
