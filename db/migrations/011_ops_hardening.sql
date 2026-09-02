-- =============================================================================
-- Migration 011: Ops / security hardening (no new product tables)
--
-- 1. admin_set_role EXECUTE only for service_role (F-015)
-- 2. Phone lookup matches last-10 digits (E.164 vs 10-digit storage)
-- 3. open_lots_for_user — inbound SMS must not SELECT lots as a table scan
-- 4. markets lat/lng CHECK (F-067)
-- 5. Alert cooldown / expiry indexes (F-068)
-- =============================================================================

revoke execute on function public.admin_set_role(uuid, text) from public, anon, authenticated;
grant execute on function public.admin_set_role(uuid, text) to service_role;

create or replace function public.lookup_profile_by_phone(p_phone text)
returns table (
    id uuid,
    preferred_language text,
    lat numeric,
    lng numeric,
    district text,
    name text
)
language sql
stable
security definer
set search_path = public
as $$
    select u.id, u.preferred_language, u.lat, u.lng, u.district, u.name
    from public.user_profiles u
    where u.phone = p_phone
       or (
            length(regexp_replace(coalesce(p_phone, ''), '[^0-9]', '', 'g')) >= 10
            and right(regexp_replace(coalesce(u.phone, ''), '[^0-9]', '', 'g'), 10)
              = right(regexp_replace(p_phone, '[^0-9]', '', 'g'), 10)
       )
    limit 1;
$$;
revoke execute on function public.lookup_profile_by_phone(text) from public, anon, authenticated;
grant execute on function public.lookup_profile_by_phone(text) to service_role;

create or replace function public.open_lots_for_user(p_user_id uuid)
returns setof public.lots
language sql
stable
security definer
set search_path = public
as $$
    select *
    from public.lots
    where user_id = p_user_id
      and status in ('open', 'offered');
$$;
revoke execute on function public.open_lots_for_user(uuid) from public, anon, authenticated;
grant execute on function public.open_lots_for_user(uuid) to service_role;

alter table public.markets drop constraint if exists chk_markets_lat;
alter table public.markets
    add constraint chk_markets_lat check (lat >= -90 and lat <= 90);
alter table public.markets drop constraint if exists chk_markets_lng;
alter table public.markets
    add constraint chk_markets_lng check (lng >= -180 and lng <= 180);

create index if not exists idx_alerts_last_notified
    on public.alerts (last_notified_at);
create index if not exists idx_alerts_expires_at
    on public.alerts (expires_at)
    where active = true;
