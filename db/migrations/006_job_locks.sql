-- =============================================================================
-- Migration 006: Job Locks & Nearest Market
--
-- 1. job_locks: Safe distributed locking for PostgREST (survives restarts)
-- 2. nearest_market: Location resolution for alerts using earthdistance
-- =============================================================================

create table if not exists public.job_locks (
    job_key     text primary key,
    holder      text not null,
    acquired_at timestamptz not null default now(),
    expires_at  timestamptz not null
);

comment on table public.job_locks is 'Distributed locks for cron jobs to prevent double-execution across processes or restarts.';

-- ─────────────────────────────────────────────────────────────────────────────
-- Nearest Market RPC
-- Returns the closest active market to a given lat/lng using great-circle distance.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.nearest_market(lat double precision, lng double precision)
returns table (id uuid, name text, distance_km double precision)
language sql stable as $$
  select m.id, m.name,
         earth_distance(ll_to_earth(m.lat, m.lng), ll_to_earth(lat, lng)) / 1000.0 as distance_km
  from public.markets m
  where m.is_active
  order by 3
  limit 1;
$$;
grant execute on function public.nearest_market(double precision, double precision) to anon, authenticated;

-- ─────────────────────────────────────────────────────────────────────────────
-- Job Lock Claim & Release
-- Atomic lock claim. If a lock exists but is expired, it gets stolen.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.claim_job_lock(p_job_key text, p_holder text, p_ttl_minutes integer default 15)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_now timestamptz := now();
    v_expires_at timestamptz := v_now + (p_ttl_minutes || ' minutes')::interval;
begin
    insert into public.job_locks (job_key, holder, acquired_at, expires_at)
    values (p_job_key, p_holder, v_now, v_expires_at)
    on conflict (job_key) do update
    set holder = excluded.holder,
        acquired_at = excluded.acquired_at,
        expires_at = excluded.expires_at
    where public.job_locks.expires_at < v_now; -- Only steal if expired

    if found then
        return true;
    end if;
    
    return false;
end;
$$;

revoke execute on function public.claim_job_lock(text, text, integer) from public, anon;
grant execute on function public.claim_job_lock(text, text, integer) to service_role;

create or replace function public.release_job_lock(p_job_key text, p_holder text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    delete from public.job_locks
    where job_key = p_job_key and holder = p_holder;
end;
$$;

revoke execute on function public.release_job_lock(text, text) from public, anon;
grant execute on function public.release_job_lock(text, text) to service_role;
