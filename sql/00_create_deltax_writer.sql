----
-- DeltaX — database writer role
--
-- Run as postgres superuser (database `alex` must already exist):
--
--   psql "postgresql://postgres@HOST:5432/postgres" -v ON_ERROR_STOP=1 \
--     -f deltax/sql/00_create_deltax_writer.sql
--
-- Then:
--   psql ... -f deltax/sql/01_create_deltax_alerts.sql
--   ALTER USER deltax_writer PASSWORD '…';
----

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'deltax_writer') THEN
        CREATE ROLE deltax_writer
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION
            NOINHERIT
            CONNECTION LIMIT 5
            PASSWORD 'CHANGE_ME_deltax_writer';
    END IF;
END
$$;

COMMENT ON ROLE deltax_writer IS
    'DeltaX monitor — INSERT on deltax_alerts only';

REVOKE ALL ON DATABASE alex FROM deltax_writer;
GRANT CONNECT ON DATABASE alex TO deltax_writer;

\c alex

REVOKE ALL ON SCHEMA public FROM deltax_writer;
GRANT USAGE ON SCHEMA public TO deltax_writer;

ALTER ROLE deltax_writer SET search_path TO public;
ALTER ROLE deltax_writer SET statement_timeout TO '60s';

REVOKE CREATE ON SCHEMA public FROM deltax_writer;
