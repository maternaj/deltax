----
-- DeltaX — alert log table (alex.public)
--
-- Run as postgres or alex after 00_create_deltax_writer.sql:
--
--   psql "postgresql://alex@HOST:5432/alex" -v ON_ERROR_STOP=1 \
--     -f deltax/sql/01_create_deltax_alerts.sql
----

\c alex

CREATE TABLE IF NOT EXISTS deltax_alerts (
    alert_id              BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    opp_id                BIGINT NOT NULL,
    match_id              BIGINT NOT NULL,
    market_type           TEXT NOT NULL,
    match_name            TEXT,
    competition_name      TEXT,
    event_name            TEXT,
    opp_name              TEXT,
    baseline_odds         NUMERIC(12, 4) NOT NULL,
    current_odds          NUMERIC(12, 4) NOT NULL,
    drop_pct              NUMERIC(8, 4) NOT NULL,
    tier_window_seconds   INTEGER NOT NULL,
    tier_drop_pct         NUMERIC(8, 4) NOT NULL,
    match_url             TEXT,
    message               TEXT NOT NULL,
    telegram_ok           BOOLEAN NOT NULL DEFAULT false,
    telegram_groups       TEXT
);

CREATE INDEX IF NOT EXISTS deltax_alerts_created_at_idx
    ON deltax_alerts (created_at DESC);

CREATE INDEX IF NOT EXISTS deltax_alerts_opp_id_idx
    ON deltax_alerts (opp_id, created_at DESC);

CREATE INDEX IF NOT EXISTS deltax_alerts_match_market_idx
    ON deltax_alerts (match_id, market_type, created_at DESC);

COMMENT ON TABLE deltax_alerts IS
    'Tipsport prematch odds drop alerts emitted by DeltaX monitor';

GRANT INSERT ON TABLE deltax_alerts TO deltax_writer;
GRANT USAGE, SELECT ON SEQUENCE deltax_alerts_alert_id_seq TO deltax_writer;

----
-- Verify (as deltax_writer):
--   INSERT INTO deltax_alerts (
--     opp_id, match_id, market_type, baseline_odds, current_odds, drop_pct,
--     tier_window_seconds, tier_drop_pct, message
--   ) VALUES (1, 1, 'WINNER_3W', 2.0, 1.8, 10, 60, 10, 'test');
----
