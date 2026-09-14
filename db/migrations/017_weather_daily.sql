create table if not exists public.weather_daily (
    market_id           uuid not null references public.markets (id) on delete cascade,
    observation_date    date not null,
    precipitation_sum_mm numeric(10,2),
    temperature_2m_mean_c numeric(8,2),
    source              text not null default 'open_meteo_archive',
    created_at          timestamptz not null default now(),
    primary key (market_id, observation_date)
);
create index if not exists idx_weather_market_date
    on public.weather_daily (market_id, observation_date desc);
alter table public.weather_daily enable row level security;
create policy "weather_admin_read" on public.weather_daily for select
    to authenticated using (public.has_role('admin'));
create policy "weather_service_write" on public.weather_daily
    for all to service_role using (true) with check (true);
