#!/usr/bin/env python3
"""VPS entrypoint — DeltaX Pinnacle corner settlement (Flashscore fs_* tables)."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DELTAX_CONFIG_PATH", str(_ROOT / "config.pinnacle.yaml"))
os.environ.setdefault("DELTAX_SOURCE", "pinnacle")

from deltax.settle.pinnacle.worker import main

if __name__ == "__main__":
    main()
