#!/usr/bin/env bash
# Deprecated — use start_vps_monitor_tipsport.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Note: start_vps_worker.sh is deprecated; use start_vps_monitor_tipsport.sh" >&2
exec "$ROOT/scripts/start_vps_monitor_tipsport.sh" "${1:-}"
