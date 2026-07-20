----
-- Migration 001 — schema migration tracking table
--
-- Run once before other migrations (apply_migrations.sh does this automatically).
----

\c alex

CREATE TABLE IF NOT EXISTS deltax_schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO deltax_schema_migrations (version)
VALUES ('001_schema_migrations')
ON CONFLICT (version) DO NOTHING;
