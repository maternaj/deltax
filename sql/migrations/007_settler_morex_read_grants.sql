----
-- Migration 007 — read-only MoreX tables for Pinnacle FS match-linking
----

\c alex

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'morex_team_alias_candidates') THEN
        GRANT SELECT ON TABLE morex_team_alias_candidates TO deltax_settler;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'morex_prematch_relative_odds') THEN
        GRANT SELECT ON TABLE morex_prematch_relative_odds TO deltax_settler;
    END IF;
END $$;

INSERT INTO deltax_schema_migrations (version)
VALUES ('007_settler_morex_read_grants')
ON CONFLICT (version) DO NOTHING;
