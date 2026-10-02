----
-- Migration 005 — source column (tipsport vs pinnacle)
----

\c alex

ALTER TABLE deltax_alerts
    ADD COLUMN IF NOT EXISTS source TEXT;

COMMENT ON COLUMN deltax_alerts.source IS
    'Alert origin: tipsport, pinnacle, etc.';

CREATE INDEX IF NOT EXISTS deltax_alerts_source_pending_idx
    ON deltax_alerts (source, kickoff_at)
    WHERE result_flag = false
      AND kickoff_at IS NOT NULL;

-- Pinnacle settler reads Flashscore stats in the same DB (when present).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'fs_soccer_all') THEN
        GRANT SELECT ON TABLE fs_soccer_all TO deltax_settler;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'fs_soccer_raw') THEN
        GRANT SELECT ON TABLE fs_soccer_raw TO deltax_settler;
    END IF;
END $$;

INSERT INTO deltax_schema_migrations (version)
VALUES ('005_add_source_column')
ON CONFLICT (version) DO NOTHING;
