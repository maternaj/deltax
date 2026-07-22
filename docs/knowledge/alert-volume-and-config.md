# DeltaX alert volume — coverage, tiers, and dedup

> Status: **operational knowledge** (investigation 2026-07-21, VPS gev-plus).
> Symptom: fewer Telegram alerts than expected. Worker healthy; volume driven by config.

## Summary

The monitor pipeline (fetch → parse → in-memory history → tier evaluation → dedup → DB → Telegram) was **working correctly** on 2026-07-21: no persist or Telegram delivery failures in logs. Lower alert volume came from **feed coverage**, **drop-tier semantics**, and **dedup rules** — not from a crashed or stuck worker.

| Factor | Impact on volume |
|--------|------------------|
| Tipsport endpoint (`allEvents=false` vs soccer full) | **Largest** — ~17–28× fewer monitored selections |
| Drop tiers (`drop_pct` vs `implied_drop_pct`) | **Medium** — different sensitivity by odds level |
| Template-level dedup `(match_id, my_selection_id)` | **Medium** — one alert per match+template per cycle |
| `max_odds: 5.0` | Low — excludes longshots |
| `markets.blacklisted` (177 templates) | Low–medium — depends on list |
| `selection_ttl_seconds: 600` | Low on full feed; higher on featured feed |

## Recommended production endpoint

Documented default (also in [alert-enrichment.md](alert-enrichment.md)):

```
GET /rest/external/offer/v1/matches?idSuperSport=16&allEvents=true
```

Same bulk prematch family as `workers/prematcher.tips`. Soccer-only, full prematch catalog.

**Not equivalent:** `?allEvents=false` — featured/popular subset only.

## Feed coverage (measured 2026-07-21)

Live comparison on VPS (`TipsportClient` + `parse_selections` + current `config.yaml` market lists):

| Endpoint | Raw selections | Matches | After blacklist | Soccer processed | Wanted-template rows | Enabled + `max_odds≤5` |
|----------|----------------|---------|-----------------|------------------|----------------------|-------------------------|
| `?allEvents=false` | 3,554 | 1,222 | 3,554 | 1,530 | 1,482 | 2,630 |
| `?idSuperSport=16&allEvents=true` | 99,920 | 524 | 25,894 | 25,894 | 25,304 | 22,674 |
| `?allEvents=true` (all sports) | 134,830 | 1,270 | 60,804 | 25,894 | 25,304 | 50,223 |

Monitor log corroboration (selection counts per cycle):

| Config era | Typical `selections=` per cycle | Typical `tracked=` |
|------------|--------------------------------|--------------------|
| Soccer full `idSuperSport=16&allEvents=true` | ~73k–99k | ~23k–62k |
| Featured `allEvents=false` | ~3.4k–3.5k | ~3.5k |

Switching to `allEvents=false` alone explains most of the alert drop after 2026-07-21 ~14:18 UTC.

## Config churn on 2026-07-21 (VPS log)

Multiple restarts the same day; alert rate varied by era:

| Time (UTC) | Endpoint | Drop tiers (logged) | Alerts in era (approx.) |
|------------|----------|---------------------|-------------------------|
| 00:00–08:43 | Soccer full | `drop_pct` 10 / 15 / 20 | (mixed; day total building) |
| 08:43–12:30 | Soccer full | `drop_pct` 10 / 15 / 20 | **~105** (~26/hr) |
| 12:30–14:00 | Featured `allEvents=false` | `drop_pct` 10 / 15 / 20 | ~21 |
| 14:00–14:18 | All sports `allEvents=true` | `implied_drop_pct` 5 / 6 / 8 (`drop_pct` 0) | ~10 |
| 14:18+ | Featured `allEvents=false` | `implied_drop_pct` 5 / 6 / 8 | **~20** (~13/hr) |

Day totals from logs: **2026-07-19** 26, **2026-07-20** 367, **2026-07-21** 164 (partial day, mixed configs).

Reference day with stable soccer-full + raw tiers: **367 alerts / 24h** — shows the system can sustain high volume when configured for full coverage.

## Drop tiers: `drop_pct` vs `implied_drop_pct`

Config (`drop_tiers`) supports both; **both must pass** when thresholds are &gt; 0 (`src/deltax/drop_detector.py`). Zero disables that side of the check.

### Raw odds drop

`(baseline - current) / baseline × 100` — shortening only.

### Implied-probability drop

`(1/current - 1/baseline) × 100` — favours detecting moves on short prices.

### Sensitivity example: flat 10% raw shortening

| Baseline odds | Raw drop | Implied drop | Old tier (`drop_pct≥10`) | New tier (`implied≥5`, `drop_pct=0`) |
|---------------|----------|--------------|---------------------------|--------------------------------------|
| 1.5 → 1.35 | 10% | ~7.4% | pass | pass |
| 2.0 → 1.80 | 10% | ~5.6% | pass | pass |
| 2.5 → 2.25 | 10% | ~4.4% | pass | **fail** |
| 3.0 → 2.70 | 10% | ~3.7% | pass | **fail** |

Implied-only tiers at 5% catch **more** favourite steam and **fewer** mid-range (2.5–5.0) moves than a flat 10% raw rule.

Raw drop needed for 5% implied (approx.):

| Baseline odds | ~Raw drop required |
|---------------|-------------------|
| 1.5 | 7% |
| 2.0 | 10% |
| 2.5 | 12% |
| 3.0 | 15% |
| 4.0 | 20% |

## Dedup and re-alert (by design)

From `README.md` and `pick_market_alerts()`:

1. **One alert per `(match_id, my_selection_id)`** per evaluation cycle — among selections whose odds changed, the **highest drop** wins for that template.
2. **Market disarm** after a successful persist: no further alerts until **current odds rise above** the alerted price (`update_market_recovery`).
3. **Only changed selections** are evaluated each cycle (`changed_opp_ids`).

Implications:

- Multi-line markets (`16-TOTAL_PARTICIPANT-1`, `16-ASIAN_TOTAL-1`, …) emit **one** Telegram per match per template per wave, not one per handicap line.
- Top alerted templates on 2026-07-21: `16-TOTAL_PARTICIPANT-1`, `16-WINNER_3W-1`, `16-DRAW_NO_BET-1` — high line cardinality templates.

To alert **per selection line** would require a code change (e.g. dedup key `(match_id, opp_id)` or include `opp_number`).

## Other filters

| Setting | Default / example | Effect |
|---------|-------------------|--------|
| `monitor.max_odds` | 5.0 | Skips selections with current odds &gt; cap before tier eval |
| `markets.blacklisted` | 177 templates | Never processed; includes e.g. `16-WINNER_2W-1` |
| `markets.wanted` | 35 soccer templates | Explicit allow-list entries; **pending** is also processed |
| `markets.pending` | auto-grown | Any non-blacklisted unknown `my_selection_id` is monitored and appended to `config.yaml` |
| `monitor.selection_ttl_seconds` | 600 | Purges in-memory state when absent from feed; hurts long-window baselines on small/rotating feeds |
| `betting_enabled=false` | runtime | Suspended selections skip history updates |

`should_process()` (`src/deltax/markets.py`): everything **except blacklisted** is monitored (wanted + pending + unknown-discovered).

## Pipeline health checks

When investigating “too few alerts”, verify in order:

1. **Process up:** `./scripts/start_vps_worker.sh status`
2. **Fetch OK:** log line `Cycle OK … endpoints_failed=0`
3. **Selection count:** compare `selections=` to expected endpoint (see table above)
4. **Changes vs alerts:** many cycles with `changed=N alerts=0` is normal if tiers/dedup filter; abnormal if `changed=0` always on full feed
5. **Telegram:** `Alert … telegram_ok=True`; grep for `Telegram delivery failed` / `Failed to persist`
6. **Startup line:** logs `DeltaX monitor started endpoints=… tiers=… markets wanted=… pending=…`

2026-07-21 VPS: all checks passed; 0 persist/Telegram failures for the day.

## Tuning guide (no code changes)

### More alerts — highest leverage

1. Use soccer full endpoint: `?idSuperSport=16&allEvents=true`
2. Optionally add a second endpoint in `tipsport.endpoints` if multi-sport coverage is desired

### Tier presets

**Previous (high volume on full feed):**

```yaml
drop_tiers:
  - window_seconds: 0
    drop_pct: 10
  - window_seconds: 180
    drop_pct: 15
  - window_seconds: 300
    drop_pct: 20
```

**Current implied-only (2026-07-21 afternoon):**

```yaml
drop_tiers:
  - window_seconds: 0
    drop_pct: 0
    implied_drop_pct: 5
  - window_seconds: 180
    drop_pct: 0
    implied_drop_pct: 6
  - window_seconds: 300
    drop_pct: 0
    implied_drop_pct: 8
```

**Hybrid (stricter):** set both `drop_pct` and `implied_drop_pct` &gt; 0 — both must pass.

### Other knobs

- Raise `max_odds` or set `0` for no cap
- Review `markets.blacklisted` for intentionally excluded templates
- Increase `selection_ttl_seconds` if using featured feed and long windows matter

Restart after config change: `./scripts/start_vps_worker.sh restart`

## Related files

| File | Role |
|------|------|
| `config.yaml` | Endpoints, tiers, markets, refresh, TTL, max odds |
| `src/deltax/drop_detector.py` | History, tiers, dedup, recovery |
| `src/deltax/monitor.py` | Main loop, alert persist, Telegram |
| `src/deltax/markets.py` | wanted / pending / blacklisted |
| `workers/deltax_monitor.nohup.log` | Production cycle and alert log |
| [alert-enrichment.md](alert-enrichment.md) | DB/Telegram field gaps (separate concern) |
