----
-- DeltaX — alert log table (alex.public)
--
-- Fresh schema — drop and recreate when rolling out enrichment changes.
--
--   psql "postgresql://alex@HOST:5432/alex" -v ON_ERROR_STOP=1 \
--     -f deltax/sql/01_create_deltax_alerts.sql
----

\c alex

DROP TABLE IF EXISTS deltax_alerts;

CREATE TABLE deltax_alerts (
    alert_id                    BIGSERIAL PRIMARY KEY,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    opp_id                      BIGINT NOT NULL,
    event_id                    BIGINT NOT NULL,
    match_id                    BIGINT NOT NULL,
    my_selection_id             TEXT NOT NULL,

    match_name                  TEXT,
    home_participant            TEXT,
    visiting_participant        TEXT,
    competition_name            TEXT,
    sport_name                  TEXT,
    super_sport_name            TEXT,
    match_type                  TEXT,
    kickoff_at                  TIMESTAMPTZ,
    match_url                   TEXT,

    event_name                  TEXT,
    opp_name                    TEXT,
    opp_type                    TEXT,
    opp_number                  TEXT,
    betting_enabled_at_alert    BOOLEAN,

    odds_previous               NUMERIC(12, 4) NOT NULL,
    odds_now                    NUMERIC(12, 4) NOT NULL,
    drop_pct                    NUMERIC(8, 4) NOT NULL,
    tier_window_seconds         INTEGER NOT NULL,
    tier_drop_pct               NUMERIC(8, 4) NOT NULL,
    baseline_observed_at        TIMESTAMPTZ NOT NULL,
    current_observed_at         TIMESTAMPTZ NOT NULL,

    tipsport_snapshot           JSONB NOT NULL,

    message                     TEXT NOT NULL,
    telegram_ok                 BOOLEAN NOT NULL DEFAULT false,
    telegram_groups             TEXT
);

CREATE INDEX deltax_alerts_created_at_idx
    ON deltax_alerts (created_at DESC);

CREATE INDEX deltax_alerts_opp_id_idx
    ON deltax_alerts (opp_id, created_at DESC);

CREATE INDEX deltax_alerts_match_selection_idx
    ON deltax_alerts (match_id, my_selection_id, created_at DESC);

CREATE INDEX deltax_alerts_my_selection_id_idx
    ON deltax_alerts (my_selection_id, created_at DESC);

COMMENT ON TABLE deltax_alerts IS
    'Tipsport prematch odds drop alerts emitted by DeltaX monitor';

GRANT INSERT ON TABLE deltax_alerts TO deltax_writer;
GRANT SELECT (alert_id) ON TABLE deltax_alerts TO deltax_writer;
GRANT USAGE, SELECT ON SEQUENCE deltax_alerts_alert_id_seq TO deltax_writer;

GRANT UPDATE (telegram_ok, telegram_groups) ON TABLE deltax_alerts TO deltax_writer;

----
-- Verify (as deltax_writer):
--   INSERT INTO deltax_alerts (
--     opp_id, event_id, match_id, my_selection_id,
--     odds_previous, odds_now, drop_pct,
--     tier_window_seconds, tier_drop_pct,
--     baseline_observed_at, current_observed_at,
--     tipsport_snapshot, message
--   ) VALUES (
--     1, 1, 1, '16-WINNER_3W-1',
--     2.0, 1.8, 10, 0, 10,
--     now(), now(),
--     '{}'::jsonb, 'test'
--   ) RETURNING alert_id;
----
