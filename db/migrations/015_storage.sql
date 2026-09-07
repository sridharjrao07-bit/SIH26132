-- =============================================================================
-- Migration 015: Storage / Warehousing as a first-class resource
-- Extracts storage from logistics into dedicated facilities and bookings.
-- =============================================================================

create table if not exists public.storage_facilities (
    id            uuid primary key default gen_random_uuid(),
    district      text not null,
    name          text not null,
    capacity_qtl  numeric(12, 2) not null,
    rate_per_qtl  numeric(10, 2) not null,
    contact       text,
    lat           numeric(9, 6),
    lng           numeric(9, 6),
    is_active     boolean not null default true,
    created_at    timestamptz not null default now()
);

alter table public.storage_facilities enable row level security;
create policy "Public can read active storage facilities"
    on public.storage_facilities for select
    using (is_active = true);

-- Seed Nashik Godowns
insert into public.storage_facilities (district, name, capacity_qtl, rate_per_qtl, contact, lat, lng)
select * from (values
    ('Nashik', 'Nashik Central Godown', 10000::numeric, 7.50::numeric, '0253-270001', 20.0000::numeric, 73.7800::numeric),
    ('Nashik', 'Lasalgaon APMC Cold Storage', 5000::numeric, 15.00::numeric, '02550-250111', 20.1200::numeric, 74.3300::numeric)
) v(district, name, capacity_qtl, rate_per_qtl, contact, lat, lng)
where not exists (select 1 from public.storage_facilities s where s.name = v.name);

create table if not exists public.storage_bookings (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references public.user_profiles (id) on delete cascade,
    lot_id          uuid not null references public.lots (id) on delete cascade,
    facility_id     uuid not null references public.storage_facilities (id) on delete restrict,
    quantity_qtl    numeric(12, 2) not null check (quantity_qtl > 0),
    status          text not null default 'requested'
                        check (status in ('requested', 'confirmed', 'cancelled', 'completed')),
    storage_start_date date,
    storage_end_date   date,
    notes           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_storage_bookings_lot
    on public.storage_bookings (lot_id, status);
create index if not exists idx_storage_bookings_facility
    on public.storage_bookings (facility_id, status);
create index if not exists idx_storage_bookings_user
    on public.storage_bookings (user_id, created_at desc);

drop trigger if exists trg_storage_bookings_updated_at on public.storage_bookings;
create trigger trg_storage_bookings_updated_at
    before update on public.storage_bookings
    for each row execute function public.set_updated_at();

alter table public.storage_bookings enable row level security;

create policy "Owners read storage bookings"
    on public.storage_bookings for select
    using (auth.uid() = user_id or public.has_role('admin'));

create policy "Owners create storage bookings"
    on public.storage_bookings for insert
    with check (auth.uid() = user_id);

create policy "Owners update storage bookings"
    on public.storage_bookings for update
    using (auth.uid() = user_id or public.has_role('admin'))
    with check (auth.uid() = user_id or public.has_role('admin'));
