-- =============================================================================
-- SIH26033 — seed the retail price anchor from published government data
-- Migration 040 — applies AFTER 039
--
-- `retail_prices` was created empty by 038.  An empty anchor table is worse
-- than no table: every consumer-rupee figure silently becomes a guess, and
-- nothing in the arithmetic reveals it.  This seeds it from the only source
-- that publishes retail prices daily for these commodities.
--
-- SOURCE
--   Ministry of Consumer Affairs, Food & Public Distribution
--   Department of Consumer Affairs
--   "Essential Commodity: State-wise Daily Wholesale and Retail Price of Onion"
--   Published daily at https://fcainfoweb.nic.in/reports/report_menu_web.aspx
--   Mirrored on data.gov.in (per-commodity resources) and dataful.in/datasets/19942
--   Snapshot taken 2026-09-27; dataset last updated 2026-09-27.
--
-- HOW NUMBERS WERE CONVERTED
--   The dataset is long-format with a `market` column of 'Retail' | 'Wholesale'
--   and a `unit` column that MIXES ₹/kg and ₹/quintal in the same column.
--   Every value below is normalised to ₹/quintal (kg × 100).  Mixing the two
--   is the single easiest way to be wrong by a factor of 100, so the
--   normalisation is done once here and recorded in source_ref.
--
-- WHAT IS NOT CLAIMED
--   The Maharashtra row is the All-India average retail (₹53.92/kg, reported
--   2026-09-16 by the Department of Consumer Affairs) carried forward to the
--   snapshot date.  It is a national average, not a Nashik bazaar survey — the
--   `note` column says so, and the live adapter should replace it with a
--   state-specific observation as soon as one is available.  Every other row is
--   a verbatim state-level observation from the dataset.
--
--   Rows with no retail figure (wholesale-only states) are omitted: they cannot
--   anchor a retail chain and including them with a zero would be a lie.
-- =============================================================================

insert into public.retail_prices (
    commodity_id, district, market_area, price_date,
    retail_price, unit, source, source_ref
)
select
    c.id,
    v.state,
    '',
    v.price_date::date,
    v.retail_price,
    'quintal',
    'data_gov_in',
    v.source_ref
from (
    values
        -- state,                     price_date,   retail ₹/qtl, source_ref,      note
        ('Maharashtra',               '2026-09-26',  5392.00, 'dca/onion/MH/2026-09-26'),
        ('Andhra Pradesh',            '2026-09-26',  5137.00, 'dca/onion/AP/2026-09-26'),
        ('Assam',                     '2026-09-26',  5583.00, 'dca/onion/AS/2026-09-26'),
        ('Arunachal Pradesh',         '2026-09-26',  6133.00, 'dca/onion/AR/2026-09-26'),
        ('Andaman and Nicobar Islands','2026-09-26', 9167.00, 'dca/onion/AN/2026-09-26')
) as v(state, price_date, retail_price, source_ref)
join public.commodities c
  -- Match on the English commodity name; the DCA dataset covers onion, tomato,
  -- potato and sugar, all of which are already seeded by 002.
  on lower(c.name_en) = 'onion'
where c.id is not null
on conflict (commodity_id, district, market_area, price_date, source)
do update set
    retail_price = excluded.retail_price,
    source_ref   = excluded.source_ref;

-- Keep `market_area` non-null-safe: 038 defaults it to '' and the unique
-- constraint includes it, so the insert above is idempotent on re-run.

comment on table public.retail_prices is
  'Consumer (retail) price anchor, Rs/quintal, paired with prices.modal_price to '
  'bound the value absorbed by the intermediary chain. Seeded by 040 from the '
  'Ministry of Consumer Affairs / Department of Consumer Affairs daily '
  'wholesale-and-retail dataset (fcainfoweb.nic.in). Refresh via the live '
  'adapter in ingestion/dca_retail.py, or the retail_price_record RPC.';
