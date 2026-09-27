# deltax — runbook (gev-plus VPS)

Standalone repo at **`~/deltax/`**. Shared **`.env`** (DB + Telegram) plus per-source YAML configs.

| Worker | Script | Config | Production (Sep 2026) |
|--------|--------|--------|------------------------|
| Pinnacle monitor | `workers/deltax_monitor_pinnacle.py` | `config.pinnacle.yaml` | **ON** — soccer corners + bookings |
| Tipsport monitor | `workers/deltax_monitor_tipsport.py` | `config.tipsport.yaml` | **OFF** (set `DELTAX_TIPSPORT_ENABLED=1`) |
| Tipsport settler | `workers/deltax_settle_tipsport.py` | `config.tipsport.yaml` | **OFF** (with Tipsport) |

Host monitoring: `~/vps-ops/status.sh --brief` (deltax group: **1/1** Pinnacle monitor).

Pinnacle uses fast bulk feeds: `ru=Corners` and `ru=Bookings` (same pattern as MoreX), soccer sport 29 only, `mk=0` + `mk=1`.

Telegram alerts tag the bookmaker: **`[TIPS]`** / **`[PINN]`**. Routing is per-source via YAML (`config.tipsport.yaml` → group A, `config.pinnacle.yaml` → group B). Do not set `DELTAX_ALERT_GROUPS` in `.env` unless you want both feeds in the same group.

## Production start

```bash
cd ~/deltax
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # first time — edit DB + Telegram
./scripts/start_vps_production.sh start    # or stop | restart | status
```

Starts **Pinnacle monitor** when `config.pinnacle.yaml` is ready. Tipsport monitor + settler are **skipped** unless `DELTAX_TIPSPORT_ENABLED=1`.

### Pinnacle (QX-336) — configure before first production run

1. Copy the reference config: `cp config.pinnacle.yaml.example config.pinnacle.yaml`
2. Tune `pinnacle.sports`, `markets.wanted`, league filters
3. `./scripts/start_vps_production.sh restart`

Until `pinnacle.sports` is non-empty, production **skips** the Pinnacle worker (Tipsport unchanged). Set `DELTAX_PINNACLE_ENABLED=0` in `.env` to skip explicitly.

## Per-worker control

```bash
./scripts/start_vps_monitor_tipsport.sh {start|stop|status|restart}
./scripts/start_vps_monitor_pinnacle.sh {start|stop|status|restart}
./scripts/start_vps_settle_tipsport.sh {start|stop|status|restart}
```

Legacy wrappers (deprecated): `start_vps_worker.sh` → Tipsport monitor, `start_vps_settle.sh` → settler.

## Foreground / debug

```bash
.venv/bin/python workers/deltax_monitor_tipsport.py --once
.venv/bin/python workers/deltax_monitor_pinnacle.py --once
.venv/bin/python workers/deltax_settle_tipsport.py --once
```

## Tests

```bash
.venv/bin/pytest -q
```

See `README.md` for SQL bootstrap and `docs/qx-336-production.md` for Pinnacle rollout notes.
