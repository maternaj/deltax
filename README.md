# DeltaX

Prematch **odds drop monitors** for **Tipsport** and **Pinnacle**. Polls bookmaker feeds, tracks
selection prices in memory, detects significant shortening drops, sends HTML Telegram alerts
(`[TIPS]` / `[PINN]`), and persists alerts to PostgreSQL (`alex.deltax_alerts`).

Standalone repo at `~/deltax/` — no runtime imports from optagame.

## Workers

| Process | Entrypoint | Config | Settlement |
|---------|------------|--------|------------|
| Tipsport monitor | `workers/deltax_monitor_tipsport.py` | `config.tipsport.yaml` | — |
| Pinnacle monitor | `workers/deltax_monitor_pinnacle.py` | `config.pinnacle.yaml` | — (none yet) |
| Tipsport settler | `workers/deltax_settle_tipsport.py` | `config.tipsport.yaml` | Tipsport results API |

## Behaviour (both monitors)

| Topic | Rule |
|-------|------|
| Drop baseline | `window_seconds: 0` = previous poll; else odds at `now - window` |
| Drop formula | `(baseline - current) / baseline × 100` (shortening only) |
| Drop tiers | OR across tiers; `drop_pct` and `implied_drop_pct` must pass (0 = disabled) |
| Dedup | One alert per `(match_id, my_selection_id)` |
| Re-alert | Market disarmed after DB persist; re-arms when odds recover |
| DB | Alerts only — no interim odds storage |
| Telegram | Optional — empty `DELTAX_TELEGRAM_GROUPS` skips send, DB still records |

Tipsport-specific: tracking key = `opp_id`; markets auto-grow `pending` in config.

Pinnacle-specific: prematch only (`mk=0/1`, normal section); synthetic templates e.g. `29-0-MONEYLINE-HOME`; stable in-memory key across `line_id` moves.

## Setup

```bash
cd ~/deltax
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # edit DB + Telegram
```

### SQL (once on VPS)

See existing bootstrap under `sql/` (`00_create_deltax_writer.sql`, `02_create_deltax_settler.sql`, `01_create_deltax_alerts.sql`, migrations).

### Config files

- **`config.tipsport.yaml`** — Tipsport endpoints, tiers, markets, settler schedule
- **`config.pinnacle.yaml`** — Pinnacle sports, tiers, markets (stub until tuned; see `config.pinnacle.yaml.example`)
- **`.env`** — `DELTAX_DATABASE_URL`, `DELTAX_TELEGRAM_GROUPS`, optional overrides

Production ops: [`how_to_run.md`](how_to_run.md) · Pinnacle rollout: [`docs/qx-336-production.md`](docs/qx-336-production.md)

## Run

VPS production (all configured workers):

```bash
./scripts/start_vps_production.sh start
```

Foreground:

```bash
.venv/bin/python workers/deltax_monitor_tipsport.py
.venv/bin/python workers/deltax_monitor_pinnacle.py   # after config.pinnacle.yaml ready
.venv/bin/python workers/deltax_settle_tipsport.py --once
```

## Tests

```bash
.venv/bin/pytest -q
```

## Repo

GitHub: `https://github.com/maternaj/deltax`
