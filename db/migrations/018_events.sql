create table if not exists public.events (
    id uuid default gen_random_uuid() primary key,
    created_at timestamptz not null default now(),
    source_url text not null unique,
    headline text not null,
    event_date date not null,
    commodity_id uuid references public.commodities(id),
    district text,
    event_type text not null,
    direction text not null,
    magnitude text not null,
    confidence numeric not null,
    reasoning text not null,
    raw_text text not null,
    reviewed_by uuid references auth.users(id),
    constraint events_event_type_check check (event_type in ('weather', 'policy', 'demand', 'supply_chain', 'pest_disease')),
    constraint events_direction_check check (direction in ('up', 'down', 'uncertain')),
    constraint events_magnitude_check check (magnitude in ('minor', 'moderate', 'major')),
    constraint events_confidence_check check (confidence >= 0.0 and confidence <= 1.0)
);

create index if not exists events_commodity_date_idx on public.events (commodity_id, event_date desc);
create index if not exists events_district_date_idx on public.events (district, event_date desc);

alter table public.events enable row level security;

-- RLS Policies
-- Authenticated users with role 'admin' can select
create policy "Admins can view events" on public.events
    for select
    to authenticated
    using (public.has_role('admin'));

-- Service role has full access (INSERT, UPDATE) handled by bypassrls, but we'll add policies for completeness just in case
create policy "Service role full access" on public.events
    for all
    to service_role
    using (true)
    with check (true);
