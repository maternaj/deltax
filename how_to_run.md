# deltax — runbook (gev-plus VPS)

Standalone repo at **`~/deltax/`**. Config: **`~/deltax/.env`** + `config.yaml`
(never symlink over `.env` from another project).

Host monitoring: `~/vps-ops/status.sh --brief` (deltax group: monitor + settler).

## Production start

```bash
cd ~/deltax
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # first time — edit DB + Telegram
./scripts/start_vps_production.sh start    # or stop | restart | status
```

Starts **monitor** (prematch drop alerts) and **settler** (results / W-L). If either
is already running, `start` restarts both.

## Manual (legacy)

```bash
./scripts/start_vps_worker.sh start
./scripts/start_vps_settle.sh start
./scripts/start_vps_worker.sh status
./scripts/start_vps_settle.sh status
```

## Tests

```bash
.venv/bin/pytest -q
```

See `README.md` for SQL bootstrap, `config.yaml` tiers, and Telegram setup.
