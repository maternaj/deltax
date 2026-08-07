#!/usr/bin/env bash
# Start/stop/restart DeltaX Tipsport settler on VPS (nohup).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=worker_ctl.sh
source "$ROOT/scripts/worker_ctl.sh"
worker_ctl deltax_settle_tipsport workers/deltax_settle_tipsport.py "${1:-}" \
  DELTAX_CONFIG_PATH="$ROOT/config.tipsport.yaml" \
  DELTAX_SOURCE=tipsport
