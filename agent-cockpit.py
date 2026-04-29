#!/usr/bin/env python3
"""Compatibility wrapper for the historical ``agent-cockpit.py`` script."""

from __future__ import annotations

import sys
from pathlib import Path


src_root = Path(__file__).resolve().parent / "src"
if src_root.exists() and str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from codexdeck.app import *  # noqa: F403,E402


if __name__ == "__main__":
    main()
