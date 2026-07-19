# DeltaX

Ever-running Tipsport **prematch** odds drop monitor. Polls the bulk REST feed, tracks
selection prices in memory (`opp_id`), detects significant shortening drops, sends
HTML Telegram alerts, and persists alerts to PostgreSQL (`alex.deltax_alerts`).

All Tipsport client code lives in this repo — no runtime imports from optagame workers.

## Behaviour

| Topic | Rule |
|-------|------|
| Feed | Configurable endpoint (default soccer bulk `idSuperSport=16&allEvents=true`) |
| Tracking key | Tipsport `opp_id` (selection id) |
| Drop baseline | `window_seconds: 0` = previous poll; else odds at `now - window` |
| Drop formula | `(baseline - current) / baseline × 100` (shortening only) |
| Tiers | OR logic — any configured tier can trigger |
| Market alerts | One alert per `(match_id, market_type)` — highest drop wins |
| Re-alert | Market disarmed only after DB persist; re-arms when alerted odds recover |
| Suspended | Skip updates while `bettingEnabled=false`; resume when re-enabled |
| Missing from feed | Soft TTL eviction (default 600s), not immediate delete |
| DB | Alerts only — no interim odds storage |
| Telegram | Optional — empty `DELTAX_TELEGRAM_GROUPS` skips send, DB still records |

## Setup

```bash
cd ~/optagame/deltax
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # edit DB + Telegram
```

### SQL (once on VPS)

```bash
psql "postgresql://postgres@HOST:5432/postgres" -v ON_ERROR_STOP=1 -f sql/00_create_deltax_writer.sql
psql "postgresql://alex@HOST:5432/alex" -v ON_ERROR_STOP=1 -f sql/01_create_deltax_alerts.sql
# ALTER USER deltax_writer PASSWORD '…';
```

### Config

- `config.yaml` — endpoint, refresh interval, drop tiers, Telegram defaults
- `.env` — `DELTAX_DATABASE_URL`, `DELTAX_TELEGRAM_GROUPS`, `DELTAX_ALERT_GROUPS`

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

## Run

Foreground:

```bash
.venv/bin/python workers/deltax_monitor.py
```

VPS (nohup):

```bash
chmod +x scripts/start_vps_worker.sh
./scripts/start_vps_worker.sh start
./scripts/start_vps_worker.sh status
```

## Tests

```bash
.venv/bin/pytest -q
```

## Repo

GitHub: `https://github.com/maternaj/deltax` (nested under optagame like sharpener).
