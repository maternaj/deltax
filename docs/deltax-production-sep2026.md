# DeltaX production scope (Sep 2026)

**Status:** Active on gev-plus — Pinnacle-only, soccer corners + bookings.

## Production stack

| Worker | State | Notes |
|--------|-------|-------|
| `deltax_monitor_pinnacle.py` | **ON** | `[PINN]` Telegram group B |
| `deltax_monitor_tipsport.py` | OFF | `DELTAX_TIPSPORT_ENABLED=1` to restore |
| `deltax_settle_tipsport.py` | OFF | with Tipsport |

Monitoring: `~/vps-ops/status.sh --brief` → **deltax 1/1**.

## Pinnacle scope

- **Sport:** soccer only (id 29)
- **Markets:** corners + bookings via bulk API (`ru=Corners`, `ru=Bookings`)
- **Time buckets:** `mk=0` (all prematch) + `mk=1` (today) — 4 HTTP calls/cycle
- **Templates:** SPREAD, TOTAL, MONEYLINE (period 0)
- **Typical load:** ~380 selections/cycle (vs ~6k pre-Sep 2026 goal+tennis feed)

Config: `config.pinnacle.yaml` — `pinnacle.relative_units` is **required** (non-empty).

## Ops commands

```bash
cd ~/deltax
./scripts/start_vps_production.sh status   # expect pinnacle running
./scripts/start_vps_production.sh restart
```

## Failure semantics (Sep 2026)

- Per-feed stats logged each cycle: `Pinnacle feed ru=… mk=… status=… rows=…`
- Cycle **fails** if any `relative_unit` has all mk buckets fail (e.g. Bookings entirely down)
- Partial single-feed failure OK if other feeds succeed

## Related Linear

QX-336 (Pinnacle phase 1), QX-349 (corners API research), QX-382 (Pinnacle settler deferred).
