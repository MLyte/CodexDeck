#!/usr/bin/env python3
"""Compatibility wrapper for running CodexDeck from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC_PACKAGE = Path(__file__).resolve().parent / "src" / "codexdeck"
if _SRC_PACKAGE.exists():
    __path__ = [str(_SRC_PACKAGE)]
    src_root = str(_SRC_PACKAGE.parent)
    if src_root not in sys.path:
        sys.path.insert(0, src_root)

__version__ = "0.1.0"

from codexdeck.cli import main, print_config  # noqa: E402


if __name__ == "__main__":
    main()
