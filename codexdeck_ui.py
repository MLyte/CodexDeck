"""Compatibility imports for the historical ``codexdeck_ui`` module."""

from __future__ import annotations

import sys
from pathlib import Path


src_root = Path(__file__).resolve().parent / "src"
if src_root.exists() and str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from codexdeck.ui import *  # noqa: F403

