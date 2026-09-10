# DeltaX alert enrichment — knowledge base

> Status: **Phase 1 implemented** (schema + persist pipeline). Captured 2026-07-19; updated 2026-09-10.
> Remaining gaps: `source` column (Tipsport vs Pinnacle), `competition_id`, `market_period` as typed columns.

## Problem

`deltax_alerts` originally stored only identifiers, Czech labels, drop math, and delivery metadata. **Phase 1 enrichment added** match context, selection metadata, drop timestamps, and `tipsport_snapshot` JSONB.

Telegram still shows richer kickoff formatting than some legacy queries expect — but `kickoff_at`, `baseline_observed_at`, and related columns are persisted.

## Current state

### Endpoint

```
GET /rest/external/offer/v1/matches?idSuperSport=16&allEvents=true
```

Configured in `config.tipsport.yaml`. Same bulk prematch feed family as `workers/prematcher.tips`.

### JSON shape

```
matches[]
  └─ events[] (or mainEvent if events empty)
       └─ opps[]   → one selection per opp
```

### Parser today (`src/deltax/parser.py`)

`TrackedSelection` / `SelectionRow` — match, event, and opp fields including `event_id`, participants, sport names, `date_start`, `opp_type`, `opp_number`, `betting_enabled`. Snapshot JSON built at persist time via `tipsport_snapshot_from_tracked()`.

### DB today (`sql/01_create_deltax_alerts.sql`)

| Column group | Examples |
|--------------|----------|
| Identity | `opp_id`, `event_id`, `match_id`, `my_selection_id` |
| Match context | `match_name`, `home_participant`, `visiting_participant`, `competition_name`, `sport_name`, `kickoff_at`, `match_url` |
| Selection | `event_name`, `opp_name`, `opp_type`, `opp_number`, `betting_enabled_at_alert` |
| Drop math | `odds_previous`, `odds_now`, `drop_pct`, `implied_drop_pct`, tier columns |
| Drop timing | `baseline_observed_at`, `current_observed_at` |
| Snapshot | `tipsport_snapshot` JSONB |
| Settlement | `odds_at_off`, `selection_result`, `result_flag`, … |
| Delivery | `message`, `telegram_ok`, `telegram_groups` |

### Still not in DB (when implementing Phase 2)

- `source` — bookmaker only in Telegram prefix (`[TIPS]` / `[PINN]`) today
- `competition_id`, `market_period` as typed columns (available in JSONB snapshot)
- Pinnacle-specific snapshot shape (uses same insert path; snapshot content differs)

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

### Phase 1 — typed columns ✅ done

Implemented in `sql/01_create_deltax_alerts.sql` + `src/deltax/monitor.py` persist path. Column renames vs original design: `odds_previous` / `odds_now` (was baseline/current).

### Phase 2 — remaining typed columns (optional)

```sql
tipsport_snapshot JSONB   -- full match+event+opp dict at alert time
-- or
drop_context JSONB        -- {baseline_ts, current_ts, tier, history_tail: [{ts, odd}, ...]}
```

Use for debugging / forward compatibility. **`tipsport_snapshot JSONB` already stores match+event+opp dict at alert time.**

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
