----
-- DeltaX analytics — clean settled-alert population (run as alex)
--
-- Excludes: unsettled, expired, void, unknown, evens-close (odds_at_off=1),
--           and optional quality filters used in downstream queries.
----

\c alex

CREATE OR REPLACE VIEW deltax_analytics_clean AS
SELECT
    a.*,
    (a.odds_at_off - a.odds_now) / NULLIF(a.odds_now, 0) * 100 AS pct_drift_alert_to_off,
    (a.odds_previous - a.odds_now) / NULLIF(a.odds_previous, 0) * 100 AS pct_drop_at_alert,
    CASE
        WHEN a.selection_result = 'W' THEN a.odds_now - 1
        WHEN a.selection_result = 'L' THEN -1.0
        ELSE NULL
    END AS pnl_unit_stake_alert_odds,
    CASE
        WHEN a.selection_result = 'W' THEN a.odds_previous - 1
        WHEN a.selection_result = 'L' THEN -1.0
        ELSE NULL
    END AS pnl_unit_stake_previous_odds,
    CASE
        WHEN a.selection_result = 'W' THEN a.odds_at_off - 1
        WHEN a.selection_result = 'L' THEN -1.0
        ELSE NULL
    END AS pnl_unit_stake_off_odds,
    CASE
        WHEN a.selection_result = 'W' THEN 1.0 / a.odds_now - 1.0 / a.odds_at_off
        WHEN a.selection_result = 'L' THEN 0
        ELSE NULL
    END AS clv_implied_vs_off
FROM deltax_alerts a
WHERE a.result_flag = true
  AND a.selection_result IN ('W', 'L')
  AND a.odds_at_off IS NOT NULL
  AND a.odds_at_off_observed_at IS NOT NULL
  AND a.odds_at_off > 1.01
  AND a.implied_drop_pct >= 5
  AND a.odds_previous BETWEEN 1.5 AND 5
  AND a.odds_now BETWEEN 1.01 AND 5;

COMMENT ON VIEW deltax_analytics_clean IS
    'Settled W/L alerts with quality filters for strategy analytics';
