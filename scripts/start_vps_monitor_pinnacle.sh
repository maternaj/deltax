#!/usr/bin/env bash
# Start/stop/restart DeltaX Pinnacle monitor on VPS (nohup).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=worker_ctl.sh
source "$ROOT/scripts/worker_ctl.sh"
worker_ctl deltax_monitor_pinnacle workers/deltax_monitor_pinnacle.py "${1:-}" \
  DELTAX_CONFIG_PATH="$ROOT/config.pinnacle.yaml" \
  DELTAX_SOURCE=pinnacle
