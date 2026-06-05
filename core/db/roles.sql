-- ─────────────────────────────────────────────────────────────────────────────
-- Least-privilege "ingester" role for the Python core (decision §2.8 / §4).
--
-- Run once as a Postgres superuser, BEFORE applying schema.sql as the ingester.
-- The ingester owns and writes every tracking table; the browser's Supabase
-- `anon` role is constrained by the RLS policies in schema.sql.
--
-- Replace the password and tighten host-based auth (pg_hba) to the tailnet.
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. The ingester login role. NO superuser, NO createdb, NO bypassrls — it is
--    the table owner, so it bypasses RLS on its own tables without the attr.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingester') THEN
        CREATE ROLE ingester LOGIN PASSWORD 'CHANGE_ME';
    END IF;
END$$;

-- 2. Scope it to the tracking schema only.
GRANT USAGE, CREATE ON SCHEMA tracking TO ingester;
ALTER DEFAULT PRIVILEGES IN SCHEMA tracking
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ingester;
ALTER DEFAULT PRIVILEGES IN SCHEMA tracking
    GRANT USAGE, SELECT ON SEQUENCES TO ingester;

-- 3. Ensure the Supabase `anon` role exists for RLS policy creation. On a real
--    Supabase instance it already does; this guard makes schema.sql portable.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
END$$;

-- After this, connect as `ingester` and run db/schema.sql.
