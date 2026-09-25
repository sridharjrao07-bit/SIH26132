do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon')          then create role anon          nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='service_role')  then create role service_role  nologin noinherit bypassrls; end if;
  if not exists (select 1 from pg_roles where rolname='authenticator') then create role authenticator login password 'postgres' noinherit; end if;
end $$;
grant anon, authenticated, service_role to authenticator;

create schema if not exists auth;
create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text unique, encrypted_password text,
  raw_user_meta_data jsonb default '{}'::jsonb, created_at timestamptz default now());

create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb); $$;
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(auth.jwt() ->> 'sub', '')::uuid; $$;
create or replace function auth.role() returns text language sql stable as $$
  select coalesce(nullif(auth.jwt() ->> 'role', ''), 'anon'); $$;

grant usage on schema auth, public to anon, authenticated, service_role;

-- Supabase baseline privileges.
--
-- A real Supabase project starts with broad grants to the three API roles and
-- then narrows them: migrations 031/036 selectively `revoke insert, update,
-- delete` on the workflow tables and hand all writes to SECURITY DEFINER RPCs.
-- Without reproducing that baseline here the revokes have nothing to revoke,
-- so `test_privileges.test_revoked_table_conformance` would pass even with
-- migration 031 deleted, and no test could read a table directly as
-- `authenticated` to exercise an RLS policy (every read died with 42501 before
-- the policy was ever consulted).
--
-- The default-privileges clauses matter: migrations run after this file, so
-- tables created by 001+ pick the grants up at CREATE TABLE time.
grant all on all tables    in schema public to anon, authenticated, service_role;
grant all on all sequences in schema public to anon, authenticated, service_role;
grant all on all functions in schema public to anon, authenticated, service_role;

alter default privileges for role postgres in schema public
    grant all on tables    to anon, authenticated, service_role;
alter default privileges for role postgres in schema public
    grant all on sequences to anon, authenticated, service_role;
alter default privileges for role postgres in schema public
    grant all on functions to anon, authenticated, service_role;
