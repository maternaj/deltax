----
-- DeltaX — allow deltax_writer to update Telegram delivery columns
--
--   psql "postgresql://alex@HOST:5432/alex" -v ON_ERROR_STOP=1 \
--     -f deltax/sql/02_grant_deltax_writer_update.sql
----

\c alex

GRANT UPDATE (telegram_ok, telegram_groups) ON TABLE deltax_alerts TO deltax_writer;
