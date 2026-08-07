# DeltaX alert enrichment — knowledge base

> Status: **planned** (not implemented). Captured 2026-07-19 after first successful alerts.
> Goal: store richer context per alert — Tipsport selection snapshot + drop timing from monitor history.

## Problem

`deltax_alerts` stores identifiers, Czech labels, drop math, and delivery metadata, but drops most useful Tipsport context and all monitor-side timestamps. Telegram messages show kickoff (`date_start`) but the DB does not.

Detection works; the gap is **what we persist at alert time**.

## Current state

### Endpoint

```
GET /rest/external/offer/v1/matches?idSuperSport=16&allEvents=true
```

Configured in `config.yaml`. Same bulk prematch feed used by `workers/prematcher.tips`.

### JSON shape

```
matches[]
  └─ events[] (or mainEvent if events empty)
       └─ opps[]   → one selection per opp
```

### Parser today (`src/deltax/parser.py`)

`SelectionRow` — 12 fields extracted:

| Field | JSON path |
|-------|-----------|
| `opp_id` | `opps[].id` |
| `match_id` | `matches[].id` |
| `market_type` | derived from `mySelectionId` regex |
| `match_name` | `matches[].name` |
| `competition_name` | `matches[].nameCompetition` |
| `event_name` | `events[].name` |
| `opp_name` | `opps[].name` |
| `odd` | `opps[].odd` |
| `betting_enabled` | `opps[].bettingEnabled` |
| `match_url` | `matches[].matchUrl` |
| `my_selection_id` | `events[].mySelectionId` |
| `date_start` | `matches[].dateStart` (ms epoch) |

**Not parsed:** `events[].id`, all other match/opp fields.

### DB today (`sql/01_create_deltax_alerts.sql`)

| Column | Source |
|--------|--------|
| `alert_id`, `created_at` | DB |
| `opp_id`, `match_id`, `market_type` | `DropHit` |
| `match_name`, `competition_name`, `event_name`, `opp_name` | `SelectionRow` |
| `baseline_odds`, `current_odds`, `drop_pct` | computed in `drop_detector` |
| `tier_window_seconds`, `tier_drop_pct` | config tier |
| `match_url`, `message` | alert pipeline |
| `telegram_ok`, `telegram_groups` | delivery |

### Parsed but not stored in DB

- `date_start` — Telegram only (`messages.format_kickoff`)
- `my_selection_id` — only derived `market_type` stored
- `betting_enabled` — runtime gate only (suspended selections skip history)
- `odd` — in-memory; alert stores `current_odds` from history (should match at fire time)

### Monitor-only data (not in Tipsport JSON)

In-memory `PriceSample(ts, odd)` history in `drop_detector.py`:

| Derivable at alert | Meaning |
|--------------------|---------|
| `baseline_observed_at` | when baseline sample was taken |
| `current_observed_at` | when current sample was taken (~ poll time) |
| `previous_odds` | `history[-2].odd` when tier window = 0 (N vs N-1) |
| `seconds_since_baseline` | `current_ts - baseline_ts` |

**Naming clarity:** `baseline_odds` = original odds at window start; `current_odds` = odds at alert. Both are already stored; timestamps are not.

---

## Tipsport JSON — full field inventory

Sample inspected from `workers/prematcher.tips/samples/baseline.json`.

### Match level (~30 keys)

| JSON field | Store in alerts? | Notes |
|------------|------------------|-------|
| `id` | yes (as `match_id`) | |
| `name` | yes | |
| `matchUrl` | yes | |
| `matchType` | yes | e.g. `PREMATCH` |
| `idCompetition`, `nameCompetition` | yes | |
| `idSport`, `nameSport` | yes | filter/report |
| `idSuperSport`, `nameSuperSport` | yes | soccer = 16 |
| `homeParticipant`, `visitingParticipant` | yes | better than parsing `name` |
| `homeParticipantId`, `visitingParticipantId` | optional | |
| `dateStart` | **yes — critical** | ms epoch; add `kickoff_at` generated column |
| `dateClosed`, `datetimeClosed`, `ended` | maybe | market closed state |
| `mainEvent` | handled | fallback when `events` empty |
| `analyzes`, `stream`, `hasStatistics`, `idLiveMatch`, … | skip | low value for drop alerts |

### Event (market) level

| JSON field | Store? | Notes |
|------------|--------|-------|
| `id` | yes | `event_id` |
| `name` | yes | Czech market name |
| `mySelectionId` | yes | e.g. `16-WINNER_3W-1` — sport, market, **period** |

`mySelectionId` suffix: `-1` = full match, `-2` = half, `-0` = ET/shootout (see prematcher/inplayer docs).

### Opp (selection) level

| JSON field | Store? | Notes |
|------------|--------|-------|
| `id` | yes | `opp_id` |
| `name`, `odd` | yes | |
| `bettingEnabled` | yes at alert | `betting_enabled_at_alert` |
| `type` | yes | `1`/`2`/`o`/`u`/… |
| `oppNumber` | yes | Tipsport internal code |
| `winning` | optional | usually false prematch |
| `mostBet` | optional | popular pick flag |
| `idEvent` | skip | redundant with parent event |

---

## Reference: `tips_prematch_odds` (prematcher worker)

Closest “capture everything useful” pattern in the legacy optagame prematcher worker (reference only — deltax is standalone).

**Path:** `workers/prematcher.tips/sql/001_create_tables.sql`  
**Extractor:** `workers/prematcher.tips/prematcher_tips.py` → `extract_wanted_selections()`

Flat row per selection with match + event + opp fields plus lifecycle columns (`first_inserted_at`, `last_refreshed_at`, `last_odds_changed_at`, `odds_previous`, `refresh_cycle_id`).

**DeltaX alerts should be:** `tips_prematch_odds`-shaped **snapshot at fire time** + drop-specific timing — **not** a second live odds table.

Do not duplicate prematcher for historical curves; join on `opp_id` / `match_id` if both run on same DB.

---

## Recommended implementation

### Phase 1 — typed columns (preferred first step)

Migration: `sql/04_enrich_deltax_alerts.sql`

**Match context**

- `date_start BIGINT`
- `kickoff_at TIMESTAMPTZ GENERATED` from `date_start`
- `competition_id INT`
- `home_participant`, `visiting_participant TEXT`
- `sport_name`, `super_sport_name TEXT` (or IDs)
- `match_type TEXT`

**Market / selection context**

- `event_id BIGINT`
- `my_selection_id TEXT`
- `market_period SMALLINT` — parsed from `mySelectionId` suffix
- `opp_type TEXT`, `opp_number TEXT`
- `betting_enabled_at_alert BOOLEAN`

**Drop timing**

- `baseline_observed_at TIMESTAMPTZ`
- `current_observed_at TIMESTAMPTZ`
- `previous_odds NUMERIC(12,4)` — for tier window = 0

**Code changes**

1. Extend `SelectionRow` — mirror prematcher extract (no market filter; monitor all selections).
2. Extend `DropHit` with `baseline_ts`, `current_ts`, optional `previous_odds`.
3. Change `_baseline_for_tier()` to return `(odd, ts)` not just odd.
4. Widen `SQL_INSERT_ALERT`, `_persist_alert()`, `format_drop_alert_message()`.
5. Update `deltax_writer` column grants for new INSERT columns.
6. Tests: parser, drop detector timestamps, persist params.

**Effort:** ~half day for Phase 1.

### Phase 2 — JSONB overflow (optional)

```sql
tipsport_snapshot JSONB   -- full match+event+opp dict at alert time
-- or
drop_context JSONB        -- {baseline_ts, current_ts, tier, history_tail: [{ts, odd}, ...]}
```

Use for debugging / forward compatibility. Keep Phase 1 columns for anything queried or indexed.

### Phase 3 — do not merge with prematcher

Alerts table = **event log at drop time** only. Full odds history stays in prematcher if needed.

---

## Target alert row shape

```
-- Identity
opp_id, match_id, event_id, my_selection_id, market_type, market_period

-- Match
match_name, home_participant, visiting_participant, competition_id, competition_name
kickoff_at, match_url, match_type

-- Market / selection
event_name, opp_name, opp_type, opp_number, betting_enabled_at_alert

-- Drop
baseline_odds, current_odds, previous_odds, drop_pct
tier_window_seconds, tier_drop_pct
baseline_observed_at, current_observed_at, created_at

-- Delivery
message, telegram_ok, telegram_groups
```

---

## Open decisions (when implementing)

1. **Flat columns only** vs **columns + `tipsport_snapshot JSONB`**?
2. Store sport/competition IDs, names, or both?
3. Include `most_bet`, `winning` columns or leave in JSONB only?
4. Regenerate Telegram `message` from columns vs keep as denormalized snapshot?

---

## Related files

| File | Role |
|------|------|
| `src/deltax/parser.py` | JSON → `SelectionRow` |
| `src/deltax/drop_detector.py` | history, `DropHit`, tiers |
| `src/deltax/monitor.py` | persist pipeline |
| `src/deltax/db.py` | `SQL_INSERT_ALERT` |
| `src/deltax/messages.py` | Telegram HTML |
| `sql/01_create_deltax_alerts.sql` | current schema |
| `workers/prematcher.tips/sql/001_create_tables.sql` | reference schema |
| `workers/prematcher.tips/prematcher_tips.py` | reference extractor |
| `workers/prematcher.tips/samples/baseline.json` | real payload sample |
