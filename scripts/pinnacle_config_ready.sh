#!/usr/bin/env bash
# Return 0 when config.pinnacle.yaml has at least one sport configured.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/config.pinnacle.yaml"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" || ! -f "$CONFIG" ]]; then
  exit 1
fi
"$PYTHON" - <<'PY' "$CONFIG"
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
sports = (raw.get("pinnacle") or {}).get("sports") or []
raise SystemExit(0 if sports else 1)
PY
