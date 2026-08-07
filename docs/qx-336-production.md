# QX-336 — Pinnacle prematch monitor (production rollout)

Linear: [QX-336](https://linear.app/quantixx/issue/QX-336/pinnacle-odds-drop-monitor-adapt-pinn-insipirationpy-to-deltax-style)

## Architecture (post-refactor)

```
config.tipsport.yaml ──► deltax_monitor_tipsport.py ──► [TIPS] Telegram + deltax_alerts
                      └► deltax_settle_tipsport.py  ──► W/L settlement (Tipsport only)

config.pinnacle.yaml ──► deltax_monitor_pinnacle.py ──► [PINN] Telegram + deltax_alerts
```

Shared: `.env` (DB, Telegram groups), `drop_detector`, `monitor.py` loop, `OddsSource` adapters (`TipsportSource`, `PinnacleSource`).

Code: `src/deltax/pinnacle/` (client, parser, flatten), `src/deltax/sources.py`.

## VPS production

```bash
cd ~/deltax
.venv/bin/pip install -e ".[dev]"    # adds curl_cffi
./scripts/start_vps_production.sh start
```

| Script | Purpose |
|--------|---------|
| `scripts/start_vps_monitor_tipsport.sh` | Tipsport drop monitor |
| `scripts/start_vps_monitor_pinnacle.sh` | Pinnacle drop monitor |
| `scripts/start_vps_settle_tipsport.sh` | Tipsport results settler |
| `scripts/start_vps_production.sh` | Starts all (Pinnacle skipped until configured) |
| `scripts/pinnacle_config_ready.sh` | Exit 0 when `pinnacle.sports` non-empty |

**Pinnacle gating:** `start_vps_production.sh` starts the Pinnacle worker only when `config.pinnacle.yaml` has at least one entry in `pinnacle.sports`. Override with `DELTAX_PINNACLE_ENABLED=0` in `.env` to force skip.

## Configure Pinnacle (manual step)

1. `cp config.pinnacle.yaml.example config.pinnacle.yaml` (or edit the stub)
2. Set `pinnacle.sports` (e.g. soccer `sport_id: 29`, `market_kinds: [0, 1]`)
3. Tune `markets.wanted` (templates like `29-0-MONEYLINE-HOME`)
4. Optional: league allow/block lists per sport
5. `./scripts/start_vps_production.sh restart`

Reference sport IDs: probe with `scripts/pinnacle_list_sports.py` (if added) or one-shot fetch documented in issue notes. Known prematch IDs (2026-08): 29 soccer, 4 basketball, 33 tennis, 15 football, 22 MMA, etc.

## Host monitoring (vps-ops)

`~/vps-ops/status.sh` deltax group checks:

- `deltax_monitor_tipsport.py`
- `deltax_monitor_pinnacle.py`
- `deltax_settle_tipsport.py`

## Validation performed

| Check | Result |
|-------|--------|
| Live Pinnacle fetch (mk=0/1) | OK — 7k+ soccer selections |
| 5-min soak (in-process) | 14 alerts, Telegram OK |
| Tipsport production path | Unchanged behaviour |
| Unit tests | 100+ passing |

## Not in scope (QX-336 phase 1)

- Pinnacle settlement worker
- `source` column on `deltax_alerts` (bookmaker only in Telegram message today)
- Per-match Pinnacle detail fetch in hot path

## Renames (breaking for ops scripts)

| Old | New |
|-----|-----|
| `config.yaml` | `config.tipsport.yaml` |
| `workers/deltax_monitor.py` | `workers/deltax_monitor_tipsport.py` |
| `workers/deltax_settle.py` | `workers/deltax_settle_tipsport.py` |
| `workers/deltax_pinnacle_monitor.py` | `workers/deltax_monitor_pinnacle.py` |

Deprecated wrappers: `start_vps_worker.sh`, `start_vps_settle.sh` → forward to new scripts.

Log/pid files: `workers/deltax_monitor_tipsport.nohup.log`, `workers/deltax_monitor_pinnacle.nohup.log`, `workers/deltax_settle_tipsport.nohup.log`.

## Deploy checklist

1. Pull deltax branch with QX-336 changes
2. `.venv/bin/pip install -e ".[dev]"`
3. Rename local `config.yaml` → `config.tipsport.yaml` if upgrading in place
4. Add `config.pinnacle.yaml` from example when ready
5. `./scripts/start_vps_production.sh restart`
6. `~/vps-ops/status.sh --brief` — expect deltax 2/2 until Pinnacle configured, then 3/3
