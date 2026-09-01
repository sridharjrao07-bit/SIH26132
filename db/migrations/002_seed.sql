-- =============================================================================
-- SIH26132 — Krishi Bazaar: Seed Migration 002
-- Seed data for Nashik district demo
-- Run AFTER 001_schema.sql
--
-- Seeds:
--   - 5 major Nashik mandis (Lasalgaon, Pimpalgaon, Yeola, Nashik, Manmad)
--   - 4 commodities (Onion, Tomato, Soybean, Maize) with Marathi + Hindi names
--   - commodity_alias rows for data.gov.in / Agmarknet / SMS spellings
--   - Sample historical price rows (last 30 days, Lasalgaon onion)
--   - One sample forecast row
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- MARKETS — 5 major Nashik APMCs
--
-- Lasalgaon: Asia's largest onion market. The demo story ("Ramesh grows onion
--   in Lasalgaon") is grounded here.
-- Pimpalgaon Baswant: second-largest onion APCM in Maharashtra.
-- Yeola: known for onion, tomato and grapes.
-- Nashik city: district headquarters, handles diverse produce.
-- Manmad: northern Nashik, key for soybean and maize from Marathwada border.
--
-- Coordinates are approximate town centroids from OpenStreetMap.
-- source_code = exact string used in data.gov.in filters[market] parameter.
-- ─────────────────────────────────────────────────────────────────────────────
insert into public.markets (name, district, state, taluka, lat, lng, source_code, is_active)
values
    ('Lasalgaon APCM',         'Nashik', 'Maharashtra', 'Niphad',   20.1201, 74.3374, 'Lasalgaon',          true),
    ('Pimpalgaon Baswant APCM','Nashik', 'Maharashtra', 'Niphad',   20.0500, 74.2700, 'Pimpalgaon(Niphad)', true),
    ('Yeola APCM',             'Nashik', 'Maharashtra', 'Yeola',    20.0440, 74.4880, 'Yeola',              true),
    ('Nashik APCM',            'Nashik', 'Maharashtra', 'Nashik',   20.0059, 73.7797, 'Nashik',             true),
    ('Manmad APCM',            'Nashik', 'Maharashtra', 'Nandgaon', 20.2540, 74.4390, 'Manmad',             true)
on conflict do nothing;


-- ─────────────────────────────────────────────────────────────────────────────
-- COMMODITIES — 4 crops with trilingual names + sanity price bands
--
-- sanity_min / sanity_max are per-quintal Rs bands that define plausible prices.
-- A validation failure (price outside this band) is logged as 'rejected' in
-- ingestion_log. Bands are deliberately wide to handle legitimate price spikes
-- (onion prices can crash to Rs 200 in a glut or spike to Rs 8000 in a shortage).
--
-- name_mr (Marathi) / name_hi (Hindi) drive i18n in API responses and SMS.
-- ─────────────────────────────────────────────────────────────────────────────
insert into public.commodities (name_en, name_mr, name_hi, category, standard_unit, sanity_min, sanity_max)
values
    -- Onion: most critical crop in Nashik. Prices swing violently (Rs 200-8000/qt).
    ('Onion',   'कांदा',    'प्याज',   'vegetable', 'quintal', 100,   8000),

    -- Tomato: volatile, perishable, 2-3 crops/year in Nashik.
    ('Tomato',  'टोमॅटो',  'टमाटर',   'vegetable', 'quintal', 100,   10000),

    -- Soybean: kharif oilseed, MSP-influenced pricing.
    ('Soybean', 'सोयाबीन', 'सोयाबीन', 'oilseed',   'quintal', 2000,  8000),

    -- Maize: kharif cereal, feed grain, relatively stable prices.
    ('Maize',   'मका',     'मक्का',   'cereal',    'quintal', 800,   3000)
on conflict (name_en) do nothing;


-- ─────────────────────────────────────────────────────────────────────────────
-- COMMODITY ALIASES
-- Maps source-specific spellings to our internal commodity_id.
-- data.gov.in uses English spellings; SMS keywords are English + Marathi.
-- Add more rows as you discover new source spellings — no code change needed.
-- ─────────────────────────────────────────────────────────────────────────────
insert into public.commodity_alias (source, source_key, commodity_id)
select 'data_gov_in', 'Onion',           id from public.commodities where name_en = 'Onion'
union all
select 'data_gov_in', 'Onion(Red)',       id from public.commodities where name_en = 'Onion'
union all
select 'data_gov_in', 'Onion (Red)',      id from public.commodities where name_en = 'Onion'
union all
select 'data_gov_in', 'Tomato',           id from public.commodities where name_en = 'Tomato'
union all
select 'data_gov_in', 'Tomato(Round)',    id from public.commodities where name_en = 'Tomato'
union all
select 'data_gov_in', 'Soyabean',         id from public.commodities where name_en = 'Soybean'
union all
select 'data_gov_in', 'Soybean',          id from public.commodities where name_en = 'Soybean'
union all
select 'data_gov_in', 'Maize',            id from public.commodities where name_en = 'Maize'
union all
-- Agmarknet spellings (sometimes different from data.gov.in)
select 'agmarknet', 'Onion',              id from public.commodities where name_en = 'Onion'
union all
select 'agmarknet', 'Pyaj',              id from public.commodities where name_en = 'Onion'
union all
select 'agmarknet', 'Tomato',            id from public.commodities where name_en = 'Tomato'
union all
select 'agmarknet', 'Soyabean',          id from public.commodities where name_en = 'Soybean'
union all
select 'agmarknet', 'Maize',             id from public.commodities where name_en = 'Maize'
union all
-- SMS inbound keywords (English + Marathi)
select 'sms', 'ONION',                   id from public.commodities where name_en = 'Onion'
union all
select 'sms', 'कांदा',                  id from public.commodities where name_en = 'Onion'
union all
select 'sms', 'TOMATO',                  id from public.commodities where name_en = 'Tomato'
union all
select 'sms', 'टोमॅटो',               id from public.commodities where name_en = 'Tomato'
union all
select 'sms', 'SOYBEAN',                 id from public.commodities where name_en = 'Soybean'
union all
select 'sms', 'सोयाबीन',               id from public.commodities where name_en = 'Soybean'
union all
select 'sms', 'MAIZE',                   id from public.commodities where name_en = 'Maize'
union all
select 'sms', 'मका',                    id from public.commodities where name_en = 'Maize'
union all
select 'sms', 'PYAJ',                    id from public.commodities where name_en = 'Onion'
union all
select 'sms', 'प्याज',                 id from public.commodities where name_en = 'Onion'
on conflict (source, source_key) do nothing;


-- ─────────────────────────────────────────────────────────────────────────────
-- SAMPLE PRICE DATA — 30 days of Lasalgaon onion prices
-- This seed data is used by:
--   (a) the forecasting engine (needs >= 10 observations to generate a forecast)
--   (b) the demo script (seed_demo.py calls forecast + alert on this data)
--   (c) offline demo when venue Wi-Fi is unavailable
--
-- Prices are realistic approximations of the Aug–Sep 2025 onion season in Nashik.
-- source='data_gov_in' with source_ref matching the typical data.gov.in record ID format.
-- ─────────────────────────────────────────────────────────────────────────────
do $$
declare
    v_market_id     uuid;
    v_commodity_id  uuid;
    v_base_price    numeric := 1800;   -- Starting modal price (Rs/quintal)
    v_day           integer;
    v_delta         numeric;
    v_modal         numeric;
    v_min           numeric;
    v_max           numeric;
    v_date          date;
begin
    select id into v_market_id    from public.markets     where source_code = 'Lasalgaon';
    select id into v_commodity_id from public.commodities where name_en = 'Onion';

    for v_day in 1..30 loop
        v_date := current_date - (31 - v_day);

        -- Simulate realistic price movement (seasonal decline mid-Aug, recovery end-Aug)
        v_delta := case
            when v_day between 1  and 10 then -30 + (random() * 60 - 30)
            when v_day between 11 and 20 then -20 + (random() * 80 - 30)
            else                               20 + (random() * 100 - 20)
        end;

        v_modal := greatest(200, v_base_price + v_delta);
        v_min   := v_modal * 0.85;
        v_max   := v_modal * 1.15;

        insert into public.prices (
            market_id, commodity_id, arrival_date,
            min_price, max_price, modal_price,
            unit, arrival_qty, variety, grade, source, source_ref,
            raw_payload
        ) values (
            v_market_id, v_commodity_id, v_date,
            round(v_min, 2), round(v_max, 2), round(v_modal, 2),
            'quintal',
            round((500 + random() * 1000)::numeric, 2),  -- 500-1500 qtl arrivals
            'General', 'General',
            'data_gov_in',
            'seed-lasalgaon-onion-' || v_date::text,
            jsonb_build_object(
                'state', 'Maharashtra', 'district', 'Nashik',
                'market', 'Lasalgaon', 'commodity', 'Onion',
                'variety', 'General', 'grade', 'General',
                'arrival_date', v_date::text,
                'min_price', round(v_min, 2),
                'max_price', round(v_max, 2),
                'modal_price', round(v_modal, 2),
                '_note', 'seeded for demo'
            )
        )
        on conflict on constraint uq_price_record do nothing;

        v_base_price := v_modal;
    end loop;
end;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- SAMPLE PRICE DATA — 15 days of Lasalgaon tomato prices
-- ─────────────────────────────────────────────────────────────────────────────
do $$
declare
    v_market_id     uuid;
    v_commodity_id  uuid;
    v_base_price    numeric := 1200;
    v_day           integer;
    v_modal         numeric;
    v_date          date;
begin
    select id into v_market_id    from public.markets     where source_code = 'Lasalgaon';
    select id into v_commodity_id from public.commodities where name_en = 'Tomato';

    for v_day in 1..15 loop
        v_date  := current_date - (16 - v_day);
        v_modal := greatest(100, v_base_price + (-50 + random() * 150 - 50));

        insert into public.prices (
            market_id, commodity_id, arrival_date,
            min_price, max_price, modal_price,
            unit, variety, grade, source, source_ref, raw_payload
        ) values (
            v_market_id, v_commodity_id, v_date,
            round(v_modal * 0.85, 2), round(v_modal * 1.15, 2), round(v_modal, 2),
            'quintal', 'General', 'General',
            'data_gov_in',
            'seed-lasalgaon-tomato-' || v_date::text,
            jsonb_build_object('commodity', 'Tomato', 'market', 'Lasalgaon', '_note', 'seeded')
        )
        on conflict on constraint uq_price_record do nothing;

        v_base_price := v_modal;
    end loop;
end;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- INGESTION LOG — record that this seed was a successful "manual" run
-- ─────────────────────────────────────────────────────────────────────────────
insert into public.ingestion_log (source, status, records_seen, records_written, records_rejected, filters)
values
    ('manual_seed', 'success', 45, 45, 0, '{"district": "Nashik", "note": "002_seed.sql initial seed"}'::jsonb);


-- ─────────────────────────────────────────────────────────────────────────────
-- USEFUL QUERIES FOR VERIFICATION
-- Run these in the Supabase SQL editor after applying both migrations:
--
-- Check market count:
--   select count(*) from public.markets;  -- expect 5
--
-- Check commodity names:
--   select name_en, name_mr, name_hi from public.commodities;
--
-- Check alias coverage:
--   select source, count(*) from public.commodity_alias group by source;
--
-- Check price rows:
--   select commodity_id, count(*), min(arrival_date), max(arrival_date)
--   from public.prices group by commodity_id;
--
-- Check earthdistance (nearest markets to Nashik city):
--   select name, round(earth_distance(ll_to_earth(lat,lng), ll_to_earth(20.0059,73.7797))::numeric/1000, 1) as km
--   from public.markets where is_active order by km;
--
-- Check RLS (run as anon — should see prices):
--   set role anon;
--   select count(*) from public.prices;   -- should return rows
--   select count(*) from public.ingestion_log;  -- should be 0 (blocked by RLS)
--   reset role;
-- ─────────────────────────────────────────────────────────────────────────────
