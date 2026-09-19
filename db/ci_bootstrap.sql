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
