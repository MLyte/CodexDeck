"""Command-line entrypoint for CodexDeck."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codexdeck import __version__
from codexdeck.app import main as run_app
from codexdeck.core import CockpitConfig


SENSITIVE_MARKERS = ("token", "api_key", "apikey", "password", "secret")


def _mask_sensitive(value: str) -> str:
    parts = value.split()
    masked: list[str] = []
    hide_next = False
    for part in parts:
        lowered = part.lower()
        if hide_next:
            masked.append("***")
            hide_next = False
            continue
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            if "=" in part:
                key, _sep, _raw = part.partition("=")
                masked.append(f"{key}=***")
            else:
                masked.append(part)
                hide_next = True
            continue
        masked.append(part)
    return " ".join(masked)


def print_config() -> None:
    config = CockpitConfig.from_env(base_dir=Path.cwd())
    rows = {
        "todo_path": str(config.todo_path),
        "log_path": str(config.log_path),
        "user_log_path": str(config.user_log_path),
        "codex_cmd": _mask_sensitive(config.codex_cmd),
        "model": config.model,
        "models": ", ".join(config.models),
        "fast_model": config.fast_model,
        "permission": config.permission,
        "permissions": ", ".join(config.permissions),
        "run_timeout": str(config.run_timeout),
        "stop_timeout": str(config.stop_timeout),
        "refresh_hz": str(config.refresh_hz),
        "max_log_lines": str(config.max_log_lines),
    }
    for key, value in rows.items():
        print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codexdeck",
        description="A local terminal cockpit for running Codex against an AI_TODO.md plan.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print the resolved CodexDeck configuration and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"codexdeck {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.print_config:
        print_config()
        return
    run_app()

