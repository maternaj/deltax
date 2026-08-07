#!/usr/bin/env python3
"""VPS entrypoint — DeltaX Tipsport alert settlement worker."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DELTAX_CONFIG_PATH", str(_ROOT / "config.tipsport.yaml"))
os.environ.setdefault("DELTAX_SOURCE", "tipsport")

from deltax.settle.worker import main

if __name__ == "__main__":
    main()
