----
-- DeltaX — database settler role
--
-- Run as postgres superuser (database `alex` must already exist):
--
--   psql "postgresql://postgres@HOST:5432/postgres" -v ON_ERROR_STOP=1 \
--     -f deltax/sql/02_create_deltax_settler.sql
--
-- Then apply migrations or bootstrap 01_create_deltax_alerts.sql for grants.
----

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'deltax_settler') THEN
        CREATE ROLE deltax_settler
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION
            NOINHERIT
            CONNECTION LIMIT 5
            PASSWORD 'CHANGE_ME_deltax_settler';
    END IF;
END
$$;

COMMENT ON ROLE deltax_settler IS
    'DeltaX settle worker — SELECT alerts, UPDATE settlement columns';

REVOKE ALL ON DATABASE alex FROM deltax_settler;
GRANT CONNECT ON DATABASE alex TO deltax_settler;

\c alex

REVOKE ALL ON SCHEMA public FROM deltax_settler;
GRANT USAGE ON SCHEMA public TO deltax_settler;

ALTER ROLE deltax_settler SET search_path TO public;
ALTER ROLE deltax_settler SET statement_timeout TO '120s';

REVOKE CREATE ON SCHEMA public FROM deltax_settler;
