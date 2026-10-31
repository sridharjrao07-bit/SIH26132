-- 044: Add Nampur, which is returned by the current data.gov.in Nashik feed.
-- Keep this forward-only: 002_seed.sql is already applied in deployed DBs.

INSERT INTO public.markets
    (name, district, state, taluka, lat, lng, source_code, is_active)
SELECT 'Nampur APCM', 'Nashik', 'Maharashtra', 'Baglan', 20.5610, 74.2590, 'Nampur', true
WHERE NOT EXISTS (
    SELECT 1 FROM public.markets WHERE source_code = 'Nampur'
);
