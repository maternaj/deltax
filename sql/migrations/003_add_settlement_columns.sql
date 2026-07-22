----
-- Migration 003 — settlement columns on deltax_alerts
--
-- selection_result codes: W/L/V/?/E (E = expired outside API window)
-- Fresh installs: sql/01_create_deltax_alerts.sql includes these columns.
----

\c alex

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS odds_at_off NUMERIC(12, 4);

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS odds_at_off_observed_at TIMESTAMPTZ;

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS selection_result CHAR(1);

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS result_flag BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS result_settled_at TIMESTAMPTZ;

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS result_source TEXT;

ALTER TABLE deltax_alerts
    DROP CONSTRAINT IF EXISTS deltax_alerts_selection_result_check;

ALTER TABLE deltax_alerts
    ADD CONSTRAINT deltax_alerts_selection_result_check
    CHECK (
        selection_result IS NULL
        OR selection_result IN ('W', 'L', 'V', '?', 'E')
    );

CREATE INDEX IF NOT EXISTS deltax_alerts_pending_settlement_idx
    ON deltax_alerts (kickoff_at)
    WHERE result_flag = false
      AND kickoff_at IS NOT NULL;

COMMENT ON COLUMN deltax_alerts.selection_result IS
    'W=win, L=loss, V=void, ?=unknown (e.g. quarter Asian), E=expired (outside settle window)';

INSERT INTO deltax_schema_migrations (version)
VALUES ('003_add_settlement_columns')
ON CONFLICT (version) DO NOTHING;
