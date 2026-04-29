#!/usr/bin/env python3
"""CodexDeck command entrypoint.

The implementation currently lives in agent-cockpit.py for backward
compatibility while the project moves to the CodexDeck name.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from codexdeck_core import CockpitConfig


SENSITIVE_MARKERS = ("token", "api_key", "apikey", "password", "secret")


def _mask_sensitive(value: str) -> str:
    parts = value.split()
    masked = []
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


def main() -> None:
    try:
        if "--print-config" in sys.argv[1:]:
            print_config()
            return
        script_path = _resolve_agent_cockpit_script()
        runpy.run_path(str(script_path), run_name="__main__")
    except KeyboardInterrupt:
        print("\nCodexDeck stopped cleanly.")
        raise SystemExit(0)


def _resolve_agent_cockpit_script() -> Path:
    candidates = [
        Path(__file__).with_name("agent-cockpit.py"),
        Path(sys.argv[0]).resolve().with_name("agent-cockpit.py"),
        Path.cwd() / "agent-cockpit.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not locate agent-cockpit.py")


if __name__ == "__main__":
    main()
