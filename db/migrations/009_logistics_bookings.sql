-- =============================================================================
-- Migration 009: Logistics bookings (storage / transport coordination)
--
-- SIH26132 expected solution includes logistics coordination, not a directory.
-- Farmers book a listed godown or truck against a lot; capacity is enforced
-- in the API from confirmed+requested quantity vs logistics_options.capacity_qtl.
-- Apply after 008_marketplace.sql.
-- =============================================================================

create table if not exists public.logistics_bookings (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references public.user_profiles (id) on delete cascade,
    lot_id          uuid not null references public.lots (id) on delete cascade,
    logistics_id    uuid not null references public.logistics_options (id) on delete restrict,
    kind            text not null check (kind in ('transport', 'storage')),
    quantity_qtl    numeric(12, 2) not null check (quantity_qtl > 0),
    status          text not null default 'requested'
                        check (status in ('requested', 'confirmed', 'cancelled', 'completed')),
    scheduled_date  date,
    notes           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

comment on table public.logistics_bookings is
  'Farmer/FPO bookings of listed storage or transport against a lot.';

create index if not exists idx_logistics_bookings_lot
    on public.logistics_bookings (lot_id, status);
create index if not exists idx_logistics_bookings_option
    on public.logistics_bookings (logistics_id, status);
create index if not exists idx_logistics_bookings_user
    on public.logistics_bookings (user_id, created_at desc);

drop trigger if exists trg_logistics_bookings_updated_at on public.logistics_bookings;
create trigger trg_logistics_bookings_updated_at
    before update on public.logistics_bookings
    for each row execute function public.set_updated_at();

alter table public.logistics_bookings enable row level security;

drop policy if exists "Owners read bookings" on public.logistics_bookings;
create policy "Owners read bookings"
    on public.logistics_bookings for select
    using (auth.uid() = user_id or public.has_role('admin'));

drop policy if exists "Owners create bookings" on public.logistics_bookings;
create policy "Owners create bookings"
    on public.logistics_bookings for insert
    with check (auth.uid() = user_id);

drop policy if exists "Owners update bookings" on public.logistics_bookings;
create policy "Owners update bookings"
    on public.logistics_bookings for update
    using (auth.uid() = user_id or public.has_role('admin'))
    with check (auth.uid() = user_id or public.has_role('admin'));
