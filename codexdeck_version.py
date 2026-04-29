"""Version resolution helpers for CodexDeck."""

from __future__ import annotations

import importlib.metadata
import re
import subprocess
from functools import lru_cache
from pathlib import Path


PACKAGE_NAMES = ("codexdeck", "CodexDeck")


@lru_cache(maxsize=1)
def resolve_version() -> str:
    for package_name in PACKAGE_NAMES:
        try:
            version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            continue
        normalized = _normalize_version(version)
        if normalized:
            return normalized

    git_version = _resolve_git_version(Path(__file__).resolve().parent)
    if git_version:
        return git_version
    return "0.0.0"


def _resolve_git_version(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--dirty", "--always", "--match", "v[0-9]*"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""

    if result.returncode != 0:
        return ""
    return _normalize_git_describe(result.stdout.strip())


def _normalize_version(version: str) -> str:
    cleaned = version.strip()
    if cleaned.startswith("v") and len(cleaned) > 1 and cleaned[1].isdigit():
        return cleaned[1:]
    return cleaned


def _normalize_git_describe(describe: str) -> str:
    if not describe:
        return ""
    dirty = describe.endswith("-dirty")
    if dirty:
        describe = describe[:-6]
    if describe.startswith("v"):
        describe = describe[1:]
    match = re.fullmatch(r"(?P<base>\d+\.\d+\.\d+)(?:-(?P<distance>\d+)-g(?P<sha>[0-9a-f]+))?", describe)
    if match:
        base = match.group("base")
        distance = match.group("distance")
        sha = match.group("sha")
        if distance and sha:
            suffix = f"+{distance}.g{sha}"
        else:
            suffix = ""
        return f"{base}{suffix}{'.dirty' if dirty else ''}"
    if re.fullmatch(r"g[0-9a-f]+", describe):
        return f"0.0.0+{describe}{'.dirty' if dirty else ''}"
    return describe + (".dirty" if dirty else "")
