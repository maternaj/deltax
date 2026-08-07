#!/usr/bin/env bash
# Shared start/stop/status for a DeltaX VPS worker (nohup + pid file).
#
# Usage (sourced or called):
#   worker_ctl.sh <worker_name> <worker_script.py> <command> [extra env KEY=VAL ...]
#
# Example:
#   worker_ctl.sh deltax_monitor_tipsport workers/deltax_monitor_tipsport.py start

set -euo pipefail

worker_ctl() {
  local worker_name="$1"
  local worker_script="$2"
  local command="$3"
  shift 3

  local root
  root="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")/.." && pwd)"
  local python="${root}/.venv/bin/python"
  local script_path="${root}/${worker_script}"
  local pid_file="${root}/workers/${worker_name}.pid"
  local log_file="${root}/workers/${worker_name}.nohup.log"
  local stop_timeout_sec="${DELTAX_WORKER_STOP_TIMEOUT_SEC:-15}"

  _log() { printf '%s\n' "$*"; }
  _err() { printf 'Error: %s\n' "$*" >&2; }

  _require_python() {
    if [[ ! -x "$python" ]]; then
      _err "Missing $python — run: python3 -m venv .venv && .venv/bin/pip install -e ."
      exit 1
    fi
    if [[ ! -f "$script_path" ]]; then
      _err "Worker script not found: $script_path"
      exit 1
    fi
  }

  _read_pid() {
    if [[ -f "$pid_file" ]]; then
      tr -d '[:space:]' < "$pid_file"
    fi
  }

  _is_running() {
    local pid
    pid="$(_read_pid || true)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null \
      && pgrep -f "${script_path}" 2>/dev/null | grep -qx "$pid"
  }

  _start() {
    _require_python
    if _is_running; then
      _log "$worker_name already running (pid $(_read_pid))"
      return 0
    fi
    mkdir -p "$(dirname "$log_file")"
    # shellcheck disable=SC2086
    nohup env "$@" "$python" "$script_path" >> "$log_file" 2>&1 &
    echo $! > "$pid_file"
    _log "Started $worker_name pid $(_read_pid) — log $log_file"
  }

  _stop() {
    local pid
    pid="$(_read_pid || true)"
    if [[ -z "$pid" ]]; then
      _log "$worker_name not running (no pid file)"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      _log "$worker_name stale pid $pid — removing pid file"
      rm -f "$pid_file"
      return 0
    fi
    kill -TERM "$pid" 2>/dev/null || true
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ "$waited" -lt "$stop_timeout_sec" ]]; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    _log "Stopped $worker_name"
  }

  _status() {
    if _is_running; then
      _log "$worker_name running pid $(_read_pid)"
    else
      _log "$worker_name not running"
    fi
    if [[ -f "$log_file" ]]; then
      _log "Last log line:"
      tail -n 1 "$log_file" || true
    fi
  }

  case "$command" in
    start) _start "$@" ;;
    stop) _stop ;;
    status) _status ;;
    restart) _stop; _start "$@" ;;
    *)
      _err "Unknown command: $command (use start|stop|status|restart)"
      return 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  worker_ctl "$@"
fi
