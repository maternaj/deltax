#!/usr/bin/env bash
# Start/stop/restart DeltaX monitor on VPS (nohup).
#
# Usage:
#   ./scripts/start_vps_worker.sh start
#   ./scripts/start_vps_worker.sh stop
#   ./scripts/start_vps_worker.sh status
#   ./scripts/start_vps_worker.sh restart

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
WORKER_NAME="deltax_monitor"
WORKER_SCRIPT="${ROOT}/workers/deltax_monitor.py"
PID_FILE="${ROOT}/workers/${WORKER_NAME}.pid"
LOG_FILE="${ROOT}/workers/${WORKER_NAME}.nohup.log"
STOP_TIMEOUT_SEC="${DELTAX_WORKER_STOP_TIMEOUT_SEC:-15}"

usage() {
  cat <<EOF
Usage: $(basename "$0") {start|stop|status|restart}

  start    Launch monitor (nohup, skip if already running)
  stop     SIGTERM, then SIGKILL if needed
  status   PID and last log line
  restart  stop then start

Repo: $ROOT
Log:  $LOG_FILE
EOF
}

log() { printf '%s\n' "$*"; }
err() { printf 'Error: %s\n' "$*" >&2; }

require_python() {
  if [[ ! -x "$PYTHON" ]]; then
    err "Missing $PYTHON — run: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
  fi
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' < "$PID_FILE"
  fi
}

is_running() {
  local pid
  pid="$(read_pid || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

cmd_start() {
  require_python
  if is_running; then
    log "$WORKER_NAME already running (pid $(read_pid))"
    return 0
  fi
  mkdir -p "$(dirname "$LOG_FILE")"
  nohup "$PYTHON" "$WORKER_SCRIPT" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  log "Started $WORKER_NAME pid $(read_pid) — log $LOG_FILE"
}

cmd_stop() {
  local pid
  pid="$(read_pid || true)"
  if [[ -z "$pid" ]]; then
    log "$WORKER_NAME not running (no pid file)"
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    log "$WORKER_NAME stale pid $pid — removing pid file"
    rm -f "$PID_FILE"
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null || true
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [[ "$waited" -lt "$STOP_TIMEOUT_SEC" ]]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  log "Stopped $WORKER_NAME"
}

cmd_status() {
  if is_running; then
    log "$WORKER_NAME running pid $(read_pid)"
  else
    log "$WORKER_NAME not running"
  fi
  if [[ -f "$LOG_FILE" ]]; then
    log "Last log line:"
    tail -n 1 "$LOG_FILE" || true
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_stop; cmd_start ;;
  *) usage; exit 1 ;;
esac
