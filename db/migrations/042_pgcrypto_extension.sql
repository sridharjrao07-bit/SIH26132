-- 042_pgcrypto_extension.sql
--
-- Make pgcrypto's gen_random_bytes reachable from the direct-channel RPCs.
--
-- WHY THIS EXISTS
-- direct_plan_commit mints a trace token with gen_random_bytes(12). The
-- function is declared `security definer set search_path = public`, so an
-- unqualified gen_random_bytes only resolves if pgcrypto lives in `public`.
-- It does not: Supabase installs it in the `extensions` schema, and a plain
-- local Postgres installs it wherever search_path happens to point. The
-- original 039 therefore worked on neither.
--
-- WHY THE SCHEMA IS EXPLICIT
-- `create extension if not exists pgcrypto;` with no schema qualifier is a
-- trap. On Supabase pgcrypto already exists in `extensions`, so the statement
-- is a no-op and the extension stays there -- fine. On a fresh local Postgres
-- it installs into `public`, and any code that then qualifies the call as
-- extensions.gen_random_bytes fails with "schema extensions does not exist".
-- Naming the schema makes the migration behave identically on both.
--
-- FORWARD-ONLY
-- Do not "fix" this by editing 039. 039 has already been applied to the live
-- database, and schema_migrations records filenames rather than checksums, so
-- an edited 039 will never re-run there. Editing it leaves the file describing
-- a migration that did not happen, and the live database carrying a hand-patched
-- substitute for it. Changes to an applied migration belong in a new file.
-- =============================================================================

begin;

-- Idempotent: a no-op where pgcrypto is already installed in this schema.
create extension if not exists pgcrypto with schema extensions;

commit;
