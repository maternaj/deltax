----
-- Migration 004 — deltax_settler grants on deltax_alerts
--
-- Requires role from sql/02_create_deltax_settler.sql (postgres superuser).
----

\c alex

GRANT SELECT ON TABLE deltax_alerts TO deltax_settler;

GRANT UPDATE (
    odds_at_off,
    odds_at_off_observed_at,
    selection_result,
    result_flag,
    result_settled_at,
    result_source
) ON deltax_alerts TO deltax_settler;

INSERT INTO deltax_schema_migrations (version)
VALUES ('004_create_deltax_settler')
ON CONFLICT (version) DO NOTHING;
