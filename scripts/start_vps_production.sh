#!/usr/bin/env bash
# DeltaX VPS production — Pinnacle monitor (soccer corners/bookings) + optional Tipsport stack.
#
# Usage:
#   ./scripts/start_vps_production.sh {start|stop|restart|status}
#
# Tipsport monitor + settler are OFF by default (Sep 2026). Set DELTAX_TIPSPORT_ENABLED=1 to restore.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '%s\n' "$*"; }

tipsport_enabled() {
  [[ "${DELTAX_TIPSPORT_ENABLED:-0}" == "1" ]]
}

any_running() {
  for script in \
    start_vps_monitor_tipsport.sh \
    start_vps_monitor_pinnacle.sh \
    start_vps_settle_tipsport.sh; do
    if "$ROOT/scripts/$script" status 2>/dev/null | grep -qE ' running pid '; then
      return 0
    fi
  done
  return 1
}

pinnacle_enabled() {
  if [[ "${DELTAX_PINNACLE_ENABLED:-1}" == "0" ]]; then
    return 1
  fi
  "$ROOT/scripts/pinnacle_config_ready.sh"
}

# Pre-refactor workers (deltax_monitor.py / deltax_settle.py) are not managed by
# worker_ctl; kill any orphans so they don't duplicate Tipsport alerts.
kill_legacy_workers() {
  local pid script
  while read -r pid script; do
    [[ -z "$pid" ]] && continue
    log "Stopping legacy worker pid $pid ($script)"
    kill "$pid" 2>/dev/null || true
  done < <(pgrep -af '[Pp]ython.*deltax/workers/deltax_(monitor|settle)\.py' 2>/dev/null \
    | grep -Ev 'monitor_tipsport|monitor_pinnacle|settle_tipsport' || true)
  rm -f "$ROOT/workers/deltax_monitor.pid" "$ROOT/workers/deltax_settle.pid"
}

cmd_stop() {
  log "Stopping deltax production..."
  kill_legacy_workers
  "$ROOT/scripts/start_vps_settle_tipsport.sh" stop || true
  "$ROOT/scripts/start_vps_monitor_pinnacle.sh" stop || true
  "$ROOT/scripts/start_vps_monitor_tipsport.sh" stop || true
}

cmd_start() {
  if any_running; then
    log "deltax already running — restarting."
    cmd_stop
  fi
  log "=== Starting deltax production ==="
  if tipsport_enabled; then
    "$ROOT/scripts/start_vps_monitor_tipsport.sh" start
    "$ROOT/scripts/start_vps_settle_tipsport.sh" start
  else
    log "Tipsport monitor + settler skipped (DELTAX_TIPSPORT_ENABLED=1 to enable)"
  fi
  if pinnacle_enabled; then
    "$ROOT/scripts/start_vps_monitor_pinnacle.sh" start
  else
    log "Pinnacle monitor skipped (configure pinnacle.sports in config.pinnacle.yaml or set DELTAX_PINNACLE_ENABLED=0 to silence)"
  fi
  cmd_status
}

cmd_status() {
  log "deltax production (repo: $ROOT)"
  if tipsport_enabled; then
    "$ROOT/scripts/start_vps_monitor_tipsport.sh" status
    "$ROOT/scripts/start_vps_settle_tipsport.sh" status
  else
    log "deltax_monitor_tipsport skipped (disabled)"
    log "deltax_settle_tipsport skipped (disabled)"
  fi
  if pinnacle_enabled; then
    "$ROOT/scripts/start_vps_monitor_pinnacle.sh" status
  else
    log "deltax_monitor_pinnacle skipped (config not ready)"
  fi
}

cmd_restart() { cmd_stop; cmd_start; }

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *) sed -n '2,5p' "$0" | sed 's/^# //'; exit 1 ;;
esac
