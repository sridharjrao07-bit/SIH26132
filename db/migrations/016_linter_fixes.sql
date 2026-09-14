-- =============================================================================
-- Migration 016: Linter Fixes
-- Addresses Supabase security linter warnings:
-- 1. Moves `cube` and `earthdistance` to the `extensions` schema.
-- 2. Secures `set_updated_at`, `nearest_market`, and `nearby_markets` with `set search_path = ''`.
-- 3. Revokes EXECUTE on internal triggers and jobs from public/anon/authenticated.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Move extensions to a dedicated schema
-- ─────────────────────────────────────────────────────────────────────────────
create schema if not exists extensions;
alter extension cube set schema extensions;
alter extension earthdistance set schema extensions;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Fix mutable search paths on functions
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create or replace function public.nearest_market(lat double precision, lng double precision)
returns table (id uuid, name text, distance_km double precision)
language sql stable
set search_path = ''
as $$
  select m.id, m.name,
         extensions.earth_distance(extensions.ll_to_earth(m.lat, m.lng), extensions.ll_to_earth(nearest_market.lat, nearest_market.lng)) / 1000.0 as distance_km
  from public.markets m
  where m.is_active
  order by 3
  limit 1;
$$;
-- Ensure we retain intended permissions (which were already set)
grant execute on function public.nearest_market(double precision, double precision) to anon, authenticated;


create or replace function public.nearby_markets(lat double precision, lng double precision, radius_km double precision default 50)
returns table (id uuid, name text, district text, lat numeric, lng numeric, distance_km double precision)
language sql stable
set search_path = ''
as $$
  select m.id, m.name, m.district, m.lat, m.lng,
         extensions.earth_distance(extensions.ll_to_earth(m.lat, m.lng), extensions.ll_to_earth(nearby_markets.lat, nearby_markets.lng)) / 1000.0 as distance_km
  from public.markets m
  where m.is_active
    and extensions.earth_distance(extensions.ll_to_earth(m.lat, m.lng), extensions.ll_to_earth(nearby_markets.lat, nearby_markets.lng)) / 1000.0 <= nearby_markets.radius_km
  order by distance_km
  limit 5;
$$;
grant execute on function public.nearby_markets(double precision, double precision, double precision) to anon, authenticated;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Revoke EXECUTE on internal triggers and jobs
-- ─────────────────────────────────────────────────────────────────────────────

-- Trigger functions shouldn't be executed directly by HTTP callers
revoke execute on function public.guard_profile_role() from public, anon, authenticated;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.set_updated_at() from public, anon, authenticated;

-- Job locks are strictly for internal service_role cron operations
revoke execute on function public.claim_job_lock(text, text, integer) from authenticated;
revoke execute on function public.release_job_lock(text, text) from authenticated;

-- (Intentional: `has_role`, `transition_payment_status`, and `transition_grievance_status`
-- remain executable by anon/authenticated as they correctly handle internal security checks
-- while being accessible to the application layer.)
