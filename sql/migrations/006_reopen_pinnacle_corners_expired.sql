----
-- Migration 006 — reopen Pinnacle corner alerts wrongly expired by 3-day Tipsport window
----

\c alex

UPDATE deltax_alerts
SET result_flag = false,
    selection_result = NULL,
    result_settled_at = NULL,
    result_source = NULL
WHERE result_source = 'expired_window'
  AND selection_result = 'E'
  AND (
    source = 'pinnacle'
    OR (
      source IS NULL
      AND my_selection_id LIKE '29-0-%'
      AND message LIKE '[PINN]%'
    )
  )
  AND (
    home_participant ILIKE '%(Corners)%'
    OR visiting_participant ILIKE '%(Corners)%'
    OR match_name ILIKE '%(Corners)%'
  )
  AND NOT (
    home_participant ILIKE '%(Bookings)%'
    OR visiting_participant ILIKE '%(Bookings)%'
    OR match_name ILIKE '%(Bookings)%'
  );

INSERT INTO deltax_schema_migrations (version)
VALUES ('006_reopen_pinnacle_corners_expired')
ON CONFLICT (version) DO NOTHING;
