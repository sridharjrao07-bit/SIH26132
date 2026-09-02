-- =============================================================================
-- Migration 008: Market linkage spine (SIH26132 expected solution)
--
-- Adds verified buyers, farmer lots, digital offers, payment tracking,
-- grievances, logistics/storage options, FPO role, unique phone,
-- and a phone-lookup RPC so inbound SMS does not need broad table rights.
-- =============================================================================

-- ── FPO role ────────────────────────────────────────────────────────────────
alter table public.user_profiles drop constraint if exists user_profiles_role_check;
alter table public.user_profiles
    add constraint user_profiles_role_check
        check (role in ('farmer', 'admin', 'buyer', 'fpo'));

-- Unique normalised phone (partial: allow multiple NULLs)
create unique index if not exists uq_user_profiles_phone
    on public.user_profiles (phone)
    where phone is not null and phone <> '';

alter table public.user_profiles
    drop constraint if exists chk_user_lat;
alter table public.user_profiles
    add constraint chk_user_lat check (lat is null or (lat >= -90 and lat <= 90));
alter table public.user_profiles
    drop constraint if exists chk_user_lng;
alter table public.user_profiles
    add constraint chk_user_lng check (lng is null or (lng >= -180 and lng <= 180));

-- admin_set_role: allow fpo
create or replace function public.admin_set_role(target_user uuid, new_role text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    if not (public.has_role('admin') or current_user = 'postgres') then
        raise exception 'admin_set_role: 403 admin required';
    end if;
    if new_role not in ('farmer', 'admin', 'buyer', 'fpo') then
        raise exception 'admin_set_role: invalid role %, must be farmer|admin|buyer|fpo', new_role;
    end if;
    perform set_config('app.skip_role_guard', 'true', true);
    update public.user_profiles
    set    role       = new_role,
           updated_at = now()
    where  id = target_user;
    if not found then
        raise exception 'admin_set_role: user % not found in user_profiles', target_user;
    end if;
end;
$$;

revoke execute on function public.admin_set_role(uuid, text) from public, anon, authenticated;
grant execute on function public.admin_set_role(uuid, text) to service_role;

-- ── Phone lookup RPC (service_role only) ────────────────────────────────────
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
    limit 1;
$$;
revoke execute on function public.lookup_profile_by_phone(text) from public, anon, authenticated;
grant execute on function public.lookup_profile_by_phone(text) to service_role;

-- ── Buyers (verified demand side) ───────────────────────────────────────────
create table if not exists public.buyers (
    id                   uuid primary key default gen_random_uuid(),
    name                 text not null,
    type                 text not null check (type in ('trader', 'processor', 'institutional', 'fpo', 'digital')),
    verified             boolean not null default false,
    phone                text,
    district             text,
    lat                  numeric(9, 6),
    lng                  numeric(9, 6),
    commodity_id         uuid references public.commodities (id) on delete set null,
    demand_qty_qtl       numeric(12, 2),
    max_price            numeric(10, 2),
    quality_requirements text,
    payment_reliability  text check (payment_reliability in ('high', 'medium', 'low')),
    created_at           timestamptz not null default now()
);

comment on table public.buyers is
  'Verified buyers (traders, processors, institutional, FPO, digital channels).';

create index if not exists idx_buyers_district on public.buyers (district);
create index if not exists idx_buyers_commodity on public.buyers (commodity_id);

alter table public.buyers enable row level security;
create policy "Public can read verified buyers"
    on public.buyers for select
    using (verified = true);
create policy "Admins write buyers"
    on public.buyers for all
    using (public.has_role('admin'))
    with check (public.has_role('admin'));

-- ── Lots (farm-gate supply) ─────────────────────────────────────────────────
create table if not exists public.lots (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references public.user_profiles (id) on delete cascade,
    fpo_id         uuid references public.user_profiles (id) on delete set null,
    commodity_id   uuid not null references public.commodities (id) on delete restrict,
    market_id      uuid references public.markets (id) on delete set null,
    quantity_qtl   numeric(12, 2) not null check (quantity_qtl > 0),
    grade          text not null default 'General',
    quality_notes  text,
    harvest_date   date,
    asking_price   numeric(10, 2) check (asking_price is null or asking_price > 0),
    status         text not null default 'open'
                       check (status in ('open', 'offered', 'matched', 'sold', 'withdrawn')),
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create index if not exists idx_lots_user on public.lots (user_id, status);
create index if not exists idx_lots_commodity on public.lots (commodity_id, status);

create trigger trg_lots_updated_at
    before update on public.lots
    for each row execute function public.set_updated_at();

alter table public.lots enable row level security;
create policy "Owners read own lots"
    on public.lots for select
    using (auth.uid() = user_id or auth.uid() = fpo_id or public.has_role('admin'));
create policy "Owners create lots"
    on public.lots for insert
    with check (auth.uid() = user_id);
create policy "Owners update lots"
    on public.lots for update
    using (auth.uid() = user_id or public.has_role('admin'))
    with check (auth.uid() = user_id or public.has_role('admin'));

-- ── Offers ──────────────────────────────────────────────────────────────────
create table if not exists public.offers (
    id            uuid primary key default gen_random_uuid(),
    lot_id        uuid not null references public.lots (id) on delete cascade,
    buyer_id      uuid not null references public.buyers (id) on delete restrict,
    user_id       uuid not null references public.user_profiles (id) on delete cascade,
    price_per_qtl numeric(10, 2) not null check (price_per_qtl > 0),
    quantity_qtl  numeric(12, 2) not null check (quantity_qtl > 0),
    status        text not null default 'pending'
                      check (status in ('pending', 'accepted', 'rejected', 'expired')),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists idx_offers_lot on public.offers (lot_id, status);
create index if not exists idx_offers_user on public.offers (user_id);

create trigger trg_offers_updated_at
    before update on public.offers
    for each row execute function public.set_updated_at();

alter table public.offers enable row level security;
create policy "Owners read offers"
    on public.offers for select
    using (auth.uid() = user_id or public.has_role('admin'));
create policy "Owners create offers"
    on public.offers for insert
    with check (auth.uid() = user_id);
create policy "Owners update offers"
    on public.offers for update
    using (auth.uid() = user_id or public.has_role('admin'));

-- ── Payments ────────────────────────────────────────────────────────────────
create table if not exists public.payments (
    id         uuid primary key default gen_random_uuid(),
    offer_id   uuid not null references public.offers (id) on delete cascade,
    user_id    uuid not null references public.user_profiles (id) on delete cascade,
    amount     numeric(12, 2) not null check (amount > 0),
    status     text not null default 'pending'
                   check (status in ('pending', 'paid', 'failed', 'disputed')),
    reference  text,
    paid_at    timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists idx_payments_user on public.payments (user_id, created_at desc);

alter table public.payments enable row level security;
create policy "Owners read payments"
    on public.payments for select
    using (auth.uid() = user_id or public.has_role('admin'));
create policy "Owners create payments"
    on public.payments for insert
    with check (auth.uid() = user_id or public.has_role('admin'));
create policy "Owners update payments"
    on public.payments for update
    using (auth.uid() = user_id or public.has_role('admin'));

-- ── Grievances ──────────────────────────────────────────────────────────────
create table if not exists public.grievances (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references public.user_profiles (id) on delete cascade,
    offer_id    uuid references public.offers (id) on delete set null,
    lot_id      uuid references public.lots (id) on delete set null,
    category    text not null check (category in ('payment', 'quality', 'logistics', 'buyer', 'other')),
    description text not null,
    status      text not null default 'open'
                    check (status in ('open', 'in_progress', 'resolved', 'rejected')),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists idx_grievances_user on public.grievances (user_id, status);

create trigger trg_grievances_updated_at
    before update on public.grievances
    for each row execute function public.set_updated_at();

alter table public.grievances enable row level security;
create policy "Owners read grievances"
    on public.grievances for select
    using (auth.uid() = user_id or public.has_role('admin'));
create policy "Owners create grievances"
    on public.grievances for insert
    with check (auth.uid() = user_id);
create policy "Owners update grievances"
    on public.grievances for update
    using (auth.uid() = user_id or public.has_role('admin'));

-- ── Logistics / storage options ─────────────────────────────────────────────
create table if not exists public.logistics_options (
    id            uuid primary key default gen_random_uuid(),
    district      text not null,
    kind          text not null check (kind in ('transport', 'storage')),
    name          text not null,
    capacity_qtl  numeric(12, 2),
    rate_per_qtl  numeric(10, 2),
    contact       text,
    lat           numeric(9, 6),
    lng           numeric(9, 6),
    is_active     boolean not null default true,
    created_at    timestamptz not null default now()
);

alter table public.logistics_options enable row level security;
create policy "Public can read logistics"
    on public.logistics_options for select
    using (is_active = true);

-- ── Seed Nashik buyers + logistics (idempotent on name+district) ────────────
insert into public.buyers (name, type, verified, district, commodity_id, demand_qty_qtl, max_price, quality_requirements, payment_reliability, lat, lng)
select 'Lasalgaon Onion Traders Association', 'trader', true, 'Nashik', c.id, 800, 2400,
       'FAQ / General grade, dry, 50kg bags', 'high', 20.1201, 74.3374
from public.commodities c where c.name_en = 'Onion'
and not exists (select 1 from public.buyers b where b.name = 'Lasalgaon Onion Traders Association');

insert into public.buyers (name, type, verified, district, commodity_id, demand_qty_qtl, max_price, quality_requirements, payment_reliability, lat, lng)
select 'Nashik Dehydration Plant', 'processor', true, 'Nashik', c.id, 1200, 2200,
       'Red onion, 40-60mm, low moisture', 'high', 20.0059, 73.7797
from public.commodities c where c.name_en = 'Onion'
and not exists (select 1 from public.buyers b where b.name = 'Nashik Dehydration Plant');

insert into public.buyers (name, type, verified, district, commodity_id, demand_qty_qtl, max_price, quality_requirements, payment_reliability, lat, lng)
select 'MSWC Institutional Desk', 'institutional', true, 'Nashik', c.id, 2000, 2300,
       'MSP-linked, weighbridge receipt required', 'high', 20.0059, 73.7797
from public.commodities c where c.name_en = 'Onion'
and not exists (select 1 from public.buyers b where b.name = 'MSWC Institutional Desk');

insert into public.buyers (name, type, verified, district, commodity_id, demand_qty_qtl, max_price, quality_requirements, payment_reliability, lat, lng)
select 'Nashik Tomato Pulp Co-op', 'processor', true, 'Nashik', c.id, 400, 1800,
       'Ripe, round variety, same-day delivery', 'medium', 20.0440, 74.4880
from public.commodities c where c.name_en = 'Tomato'
and not exists (select 1 from public.buyers b where b.name = 'Nashik Tomato Pulp Co-op');

insert into public.buyers (name, type, verified, district, commodity_id, demand_qty_qtl, max_price, quality_requirements, payment_reliability, lat, lng)
select 'eNAM Nashik Digital Desk', 'digital', true, 'Nashik', c.id, 600, 2100,
       'Assayed lots, digital weighment', 'medium', 20.0059, 73.7797
from public.commodities c where c.name_en = 'Soybean'
and not exists (select 1 from public.buyers b where b.name = 'eNAM Nashik Digital Desk');

insert into public.logistics_options (district, kind, name, capacity_qtl, rate_per_qtl, contact, lat, lng)
select * from (values
    ('Nashik', 'storage',   'MSWC Lasalgaon Godown',     5000::numeric, 8.00::numeric,  '02550-270001', 20.1201::numeric, 74.3374::numeric),
    ('Nashik', 'storage',   'Nashik APMC Cold Store',    800::numeric,  18.00::numeric, '0253-2501111', 20.0059::numeric, 73.7797::numeric),
    ('Nashik', 'transport', 'Niphad Mandi Tempo Pool',   200::numeric,  12.00::numeric, '9876500001',   20.0500::numeric, 74.2700::numeric),
    ('Nashik', 'transport', 'Manmad Truck Union',        1500::numeric, 9.50::numeric,  '9876500002',   20.2540::numeric, 74.4390::numeric)
) v(district, kind, name, capacity_qtl, rate_per_qtl, contact, lat, lng)
where not exists (select 1 from public.logistics_options l where l.name = v.name);
