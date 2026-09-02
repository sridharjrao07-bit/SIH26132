create or replace function public.nearby_markets(lat double precision, lng double precision, radius_km double precision default 50)
returns table (id uuid, name text, district text, lat numeric, lng numeric, distance_km double precision)
language sql stable as $$
  select m.id, m.name, m.district, m.lat, m.lng,
         earth_distance(ll_to_earth(m.lat, m.lng), ll_to_earth(lat, lng)) / 1000.0 as distance_km
  from public.markets m
  where m.is_active
    and earth_distance(ll_to_earth(m.lat, m.lng), ll_to_earth(lat, lng)) / 1000.0 <= radius_km
  order by distance_km
  limit 5;
$$;
grant execute on function public.nearby_markets(double precision, double precision, double precision) to anon, authenticated;
