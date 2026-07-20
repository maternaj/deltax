----
-- Migration 002 — implied-probability drop columns on deltax_alerts
--
-- Apply on existing databases that were created before implied drop tracking.
-- Fresh installs: use sql/01_create_deltax_alerts.sql (already includes these columns).
----

\c alex

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS implied_drop_pct NUMERIC(8, 4);

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS tier_implied_drop_pct NUMERIC(8, 4);

UPDATE deltax_alerts
SET implied_drop_pct = 0,
    tier_implied_drop_pct = 0
WHERE implied_drop_pct IS NULL
   OR tier_implied_drop_pct IS NULL;

ALTER TABLE deltax_alerts
    ALTER COLUMN implied_drop_pct SET NOT NULL,
    ALTER COLUMN tier_implied_drop_pct SET NOT NULL;

INSERT INTO deltax_schema_migrations (version)
VALUES ('002_add_implied_drop_pct')
ON CONFLICT (version) DO NOTHING;
