#!/usr/bin/env bash
# DeltaX VPS production — monitor + settler.
#
# Usage:
#   ./scripts/start_vps_production.sh {start|stop|restart|status}
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '%s\n' "$*"; }

any_running() {
  "$ROOT/scripts/start_vps_worker.sh" status 2>/dev/null | grep -q 'running' && return 0
  "$ROOT/scripts/start_vps_settle.sh" status 2>/dev/null | grep -q 'running' && return 0
  return 1
}

cmd_stop() {
  log "Stopping deltax production..."
  "$ROOT/scripts/start_vps_settle.sh" stop || true
  "$ROOT/scripts/start_vps_worker.sh" stop || true
}

cmd_start() {
  if any_running; then
    log "deltax already running — restarting."
    cmd_stop
  fi
  log "=== Starting deltax production ==="
  "$ROOT/scripts/start_vps_worker.sh" start
  "$ROOT/scripts/start_vps_settle.sh" start
  cmd_status
}

cmd_status() {
  log "deltax production (repo: $ROOT)"
  "$ROOT/scripts/start_vps_worker.sh" status
  "$ROOT/scripts/start_vps_settle.sh" status
}

cmd_restart() { cmd_stop; cmd_start; }

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *) sed -n '2,5p' "$0" | sed 's/^# //'; exit 1 ;;
esac
