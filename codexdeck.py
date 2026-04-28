#!/usr/bin/env python3
"""CodexDeck command entrypoint.

The implementation currently lives in agent-cockpit.py for backward
compatibility while the project moves to the CodexDeck name.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    runpy.run_path(str(Path(__file__).with_name("agent-cockpit.py")), run_name="__main__")


if __name__ == "__main__":
    main()
