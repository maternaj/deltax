----
-- DeltaX analytics — example queries (run against deltax_analytics_clean)
----

-- 1) Sport summary (your query, on clean view)
SELECT
    super_sport_name,
    COUNT(*) AS n,
    ROUND(AVG(odds_previous)::numeric, 3) AS avg_odds_prev,
    ROUND(AVG(odds_now)::numeric, 3) AS avg_odds_alert,
    ROUND(AVG(odds_at_off)::numeric, 3) AS avg_odds_off,
    ROUND(SUM(pnl_unit_stake_alert_odds)::numeric, 2) AS pnl_at_alert,
    ROUND(SUM(pnl_unit_stake_off_odds)::numeric, 2) AS pnl_at_off,
    ROUND(AVG(pct_drift_alert_to_off)::numeric, 2) AS avg_pct_drift_to_off
FROM deltax_analytics_clean
GROUP BY 1
ORDER BY n DESC;


-- 2) One row per match — first alert only (reduces same-match correlation)
WITH ranked AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (
            PARTITION BY match_id
            ORDER BY current_observed_at ASC, alert_id ASC
        ) AS rn_match
    FROM deltax_analytics_clean c
)
SELECT
    super_sport_name,
    COUNT(*) AS n_matches,
    ROUND(SUM(pnl_unit_stake_alert_odds)::numeric, 2) AS pnl_at_alert,
    ROUND(SUM(pnl_unit_stake_off_odds)::numeric, 2) AS pnl_at_off,
    ROUND(AVG(pct_drift_alert_to_off)::numeric, 2) AS avg_pct_drift
FROM ranked
WHERE rn_match = 1
GROUP BY 1
ORDER BY n_matches DESC;


-- 3) One row per (match_id, my_selection_id) — market-template dedup
WITH ranked AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (
            PARTITION BY match_id, my_selection_id
            ORDER BY current_observed_at ASC, alert_id ASC
        ) AS rn
    FROM deltax_analytics_clean c
)
SELECT
    super_sport_name,
    COUNT(*) AS n,
    ROUND(SUM(pnl_unit_stake_off_odds)::numeric, 2) AS pnl_at_off
FROM ranked
WHERE rn = 1
GROUP BY 1;


-- 4) Drift proof — odds rarely improve back to previous by kickoff
SELECT
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN odds_at_off >= odds_previous THEN 1 ELSE 0 END)::numeric, 1)
        AS pct_off_gte_previous,
    ROUND(100.0 * AVG(CASE WHEN odds_at_off <= odds_now THEN 1 ELSE 0 END)::numeric, 1)
        AS pct_off_lte_alert,
    ROUND(AVG(pct_drift_alert_to_off)::numeric, 2) AS avg_drift_pct
FROM deltax_analytics_clean;


-- 5) Match basket size — how correlated are alerts?
SELECT
    match_id,
    COUNT(*) AS alerts_in_match,
    COUNT(DISTINCT my_selection_id) AS distinct_markets,
    SUM(pnl_unit_stake_off_odds) AS match_pnl_if_all_bet
FROM deltax_analytics_clean
GROUP BY 1
ORDER BY alerts_in_match DESC
LIMIT 20;


-- 6) Bootstrap-friendly: random one alert per match (repeat in app for CI)
-- SELECT * FROM deltax_analytics_clean
-- WHERE alert_id IN (
--     SELECT DISTINCT ON (match_id) alert_id
--     FROM deltax_analytics_clean
--     ORDER BY match_id, RANDOM()
-- );
