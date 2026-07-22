# DeltaX settlement analytics — approach

> Status: initial framework (2026-07-22). Small sample — treat all P/L as indicative.

## Question split

The strategy has **two separate claims**:

| Claim | Metric | Expected if edge is real |
|-------|--------|-------------------------|
| **A. Drop is real** | `odds_at_off` vs `odds_now` / `odds_previous` | Off price ≥ alert price (shortening sticks); rarely drifts back above `odds_previous` |
| **B. Drop is profitable** | P/L at alert odds vs at off odds | Positive unit P/L at scale; positive CLV vs closing |

Your sport-level query shows **A likely holds** (avg `odds_at_off` between previous and now, or below now) while **B is mixed/negative** on flat 1u stakes — especially Fotbal with many correlated alerts.

## Clean population (exclude suspicious rows)

Use view `deltax_analytics_clean` (`sql/analytics/001_clean_population_view.sql`):

| Filter | Reason |
|--------|--------|
| `result_flag` + `selection_result IN ('W','L')` | Actionable outcomes only |
| `odds_at_off IS NOT NULL` and `> 1.01` | Exclude evens-close / line-moved-to-1.0 signal |
| `implied_drop_pct >= 5` | Strategy threshold |
| `odds_previous BETWEEN 1.5 AND 5` | Monitor band |
| Exclude `V`, `?`, `E` | Void, unknown, expired |

Optional tighten: `result_source = 'tipsport_results'`, `betting_enabled_at_alert = true`.

## Correlation problem (same match basket)

One match can produce **many alerts** (different markets + re-alerts). Summing unit P/L **overstates exposure** and inflates variance.

**Analysis lenses** (run all, compare):

1. **All alerts (raw)** — upper bound on activity; most pessimistic for P/L if edges cancel within match.
2. **First alert per `match_id`** — independent match baskets; ~1 decision per event.
3. **First alert per `(match_id, my_selection_id)`** — one per market template (dedup re-alerts).
4. **First alert per `(match_id, opp_id)`** — strictest selection-level dedup.
5. **Match-level aggregate** — sum P/L within match, count as one observation (models “bet everything on the match”).

For small *n*, prefer **(2)** or **(3)** as primary; report raw as sensitivity.

## P/L definitions (1 unit flat stake)

| Column | Formula | Interpretation |
|--------|---------|----------------|
| `pnl_unit_stake_alert_odds` | W: `odds_now - 1`, L: `-1` | Bet at alert price |
| `pnl_unit_stake_off_odds` | W: `odds_at_off - 1`, L: `-1` | Bet at closing (realistic if you could still get alert line) |
| `pnl_unit_stake_previous_odds` | W: `odds_previous - 1`, L: `-1` | Counterfactual: bet before drop |
| `clv_implied_vs_off` | W: `1/odds_now - 1/odds_at_off`, L: `0` | Implied-probability CLV vs close |

**Important:** Using `odds_at_off` for both W and L P/L assumes you bet at alert time but **mark to market at close** for wins only on stake return — for losses, `-1` is correct regardless of off price.

## Drop persistence (claim A)

```sql
-- % where closing odds still below baseline (drop stuck)
AVG(odds_at_off <= odds_previous)
-- % where closing <= alert (continued shortening or flat)
AVG(odds_at_off <= odds_now)
AVG(pct_drift_alert_to_off)  -- negative = continued shorten
```

If these are high (~70%+), the **signal is real** even when P/L is flat.

## Segmentation dimensions

Slice when *n* allows:

- `super_sport_name`, `my_selection_id` (market type)
- `tier_window_seconds` / `implied_drop_pct` bucket
- Time to kickoff at alert (from `kickoff_at - current_observed_at`)
- `drop_pct` vs `implied_drop_pct` (which tier fired)
- Pre-match vs near-kickoff (`< 60 min`)

## Statistical caution

- Current *n* ≈ 80–100 clean rows — **no firm conclusions** on P/L.
- Use **match-level bootstrap**: resample matches with replacement, sum P/L, 95% CI.
- Report **Wilson interval** on win rate, not just point estimate.
- Flag when a sport row is driven by **1–2 matches** (see match basket query).

## Suggested reporting cadence

Weekly:

1. Clean population count + pending settlement backlog
2. Drift stats (claim A) by sport
3. P/L at off odds — raw vs first-per-match — by sport
4. Top 10 match baskets by alert count (correlation check)
5. Win rate and avg CLV vs off

## Files

| File | Purpose |
|------|---------|
| `sql/analytics/001_clean_population_view.sql` | `deltax_analytics_clean` view |
| `sql/analytics/002_analysis_queries.sql` | Example queries |

Apply view once:

```bash
psql "postgresql://alex@HOST:5432/alex" -f sql/analytics/001_clean_population_view.sql
```
