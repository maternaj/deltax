# DeltaX

Ever-running Tipsport **prematch** odds drop monitor. Polls the bulk REST feed, tracks
selection prices in memory (`opp_id`), detects significant shortening drops, sends
HTML Telegram alerts, and persists alerts to PostgreSQL (`alex.deltax_alerts`).

All Tipsport client code lives in this repo — no runtime imports from optagame workers.

## Behaviour

| Topic | Rule |
|-------|------|
| Feed | One or more configurable endpoints; each refresh cycle fetches all in sequence |
| Tracking key | Tipsport `opp_id` (selection id) |
| Drop baseline | `window_seconds: 0` = previous poll; else odds at `now - window` |
| Drop formula | `(baseline - current) / baseline × 100` (shortening only) |
| Drop tiers | OR across tiers; within each tier both `drop_pct` and `implied_drop_pct` must pass (0 = disabled) |
| Dedup | One alert per `(match_id, my_selection_id)` — highest drop wins among selections with current odds at or below `max_odds` |
| Max odds | Selections with current odds above `monitor.max_odds` (default 5.0) are excluded before template winner is chosen |
| Markets | `wanted` and `pending` are monitored; `blacklisted` and `blacklisted_prefixes` are ignored; unknown `my_selection_id` values auto-added to `pending` |
| Re-alert | Market disarmed only after DB persist; re-arms when alerted odds recover |
| Suspended | Skip updates while `bettingEnabled=false`; resume when re-enabled |
| Missing from feed | Soft TTL eviction (default 600s), not immediate delete |
| DB | Alerts only — no interim odds storage |
| Settlement | `deltax_settle` worker — results API, `odds_at_off`, W/L/V/?/E |
| Telegram | Optional — empty `DELTAX_TELEGRAM_GROUPS` skips send, DB still records |

## Setup

```bash
cd ~/deltax
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # edit DB + Telegram
```

### SQL (once on VPS)

```bash
# 1. Writer role (postgres superuser)
psql "postgresql://postgres@HOST:5432/postgres" -v ON_ERROR_STOP=1 -f sql/00_create_deltax_writer.sql

# 1b. Settler role (postgres superuser)
psql "postgresql://postgres@HOST:5432/postgres" -v ON_ERROR_STOP=1 -f sql/02_create_deltax_settler.sql

# 2a. Fresh database — full bootstrap
psql "postgresql://alex@HOST:5432/alex" -v ON_ERROR_STOP=1 -f sql/01_create_deltax_alerts.sql

# 2b. Existing database — apply pending migrations only
chmod +x scripts/apply_migrations.sh
./scripts/apply_migrations.sh "postgresql://alex@HOST:5432/alex"

# ALTER USER deltax_writer PASSWORD '…';
# ALTER USER deltax_settler PASSWORD '…';
```

Schema changes after the initial bootstrap go in `sql/migrations/` as numbered files
(`002_…`, `003_…`). Each migration records itself in `deltax_schema_migrations`.
Run `02_create_deltax_settler.sql` before migrations if the settler role is not created yet.

### Config

- `config.yaml` — endpoints, refresh interval, drop tiers, min odds, market lists, Telegram defaults
- `.env` — `DELTAX_DATABASE_URL`, `DELTAX_TELEGRAM_GROUPS`, `DELTAX_ALERT_GROUPS`

Production ops: [`how_to_run.md`](how_to_run.md).

Tipsport feeds (`tipsport.endpoints` — fetched in sequence every refresh cycle):

```yaml
tipsport:
  base_url: https://www.tipsport.cz
  endpoints:
    - /rest/external/offer/v1/matches?allEvents=true
    - /rest/external/offer/v1/matches?idSuperSport=16&allEvents=true
```

Legacy single `tipsport.endpoint` still works. Override via env: `DELTAX_TIPSPORT_ENDPOINTS=/path/a,/path/b`.

Market lists in `config.yaml`:

```yaml
monitor:
  max_odds: 5.0

markets:
  wanted: []      # full my_selection_id values, e.g. 16-WINNER_3W-1
  pending: []
  blacklisted: [] # e.g. 16-WINNER_3W-2 period templates
  blacklisted_prefixes: [] # e.g. 11- ignores all markets for super-sport 11
```

Unknown `my_selection_id` values discovered at runtime are appended to `markets.pending` in `config.yaml`.

Drop tiers example:

```yaml
drop_tiers:
  - window_seconds: 60
    drop_pct: 10
  - window_seconds: 180
    drop_pct: 15
  - window_seconds: 600
    drop_pct: 20
```

Settlement worker (`deltax_settle`):

```yaml
settle:
  sleep_seconds: 900
  default_delay_hours: 6
  max_age_days: 3
  batch_match_limit: 50
  match_request_delay_seconds: 5
  market_delay_hours:
    16-GOAL_SCORERS-1: 12   # exact my_selection_id only
```

Per-alert `selection_result`: `W` / `L` / `V` (void) / `?` (quarter Asian) / `E` (expired &gt;3 days).
`odds_at_off` comes from the results API `cell.odd` (including `1.0`).

## Run

Monitor foreground:

```bash
.venv/bin/python workers/deltax_monitor.py
```

Settler foreground (one cycle):

```bash
.venv/bin/python workers/deltax_settle.py --once
```

Settler daemon:

```bash
.venv/bin/python workers/deltax_settle.py
```

VPS (nohup):

```bash
chmod +x scripts/start_vps_worker.sh scripts/start_vps_settle.sh
./scripts/start_vps_worker.sh start
./scripts/start_vps_settle.sh start
./scripts/start_vps_worker.sh status
./scripts/start_vps_settle.sh status
```

## Tests

```bash
.venv/bin/pytest -q
```

## Repo

GitHub: `https://github.com/maternaj/deltax` (standalone repo at `~/deltax/`).
