-- 041_seed_value_chain_profiles.sql
--
-- Seed public.value_chain_profiles with the engine's built-in chain models so a
-- district officer can retune the chain from the database instead of a deploy.
--
-- WHY THIS MIGRATION EXISTS
-- Migration 038 created the table; nothing ever wrote to it. The engine
-- therefore always used DEFAULT_CHAIN_PROFILES, and the claim "retune without a
-- deploy" was false. This migration makes it true by giving the table the same
-- content the code already had, so editing a row changes behaviour immediately.
--
-- WHAT IS AND IS NOT CLAIMED
-- The stage *shape* (which layer takes how much relative to the others) comes
-- from published value-chain studies and is fixed in direct/value_chain.py. The
-- *level* is calibrated per market at request time from observed prices — see
-- direct/fair_price.py calibrate_margin_scale. So these rows are a starting
-- point an operator edits, not ground truth about any particular mandi.
--
-- Rows are keyed by category with commodity_id NULL, which the engine resolves
-- as a category-level override (DirectConfig.category_chains). A row with a
-- commodity_id set takes precedence (DirectConfig.traditional_chains).
--
-- IDEMPOTENCY
-- The table's only unique constraint is a random-uuid primary key, so a plain
-- ON CONFLICT DO NOTHING has nothing to conflict on and would duplicate rows on
-- every re-run. This migration therefore first adds the natural key that was
-- always implied — (category, scope_district, channel, commodity_id) — and then
-- uses it as the conflict target.

begin;

-- The natural key. NULL commodity_id would defeat a plain unique index, so
-- coalesce it: a category-level row (commodity_id IS NULL) is one row, and
-- commodity-specific rows stay individually addressable.
create unique index if not exists uq_value_chain_profiles_scope
    on public.value_chain_profiles (
        category,
        scope_district,
        channel,
        coalesce(commodity_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );

insert into public.value_chain_profiles
    (category, scope_district, channel, stages, margin_scale, calibration_status,
     source_note, is_active)
values
    ('vegetable', '', 'traditional',
     '[{"key": "village_aggregator", "label_en": "Village trader / aggregator", "label_mr": "\u0917\u093e\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0917\u093e\u0901\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.05, "cost_per_qtl": 40.0, "loss_pct": 0.02, "essential": false, "kind": "assembly", "note": "Buys at the farm gate, assembles lots, extends credit."}, {"key": "commission_agent", "label_en": "Commission agent (arhatiya)", "label_mr": "\u0906\u0921\u0924 \u0926\u0932\u093e\u0932", "label_hi": "\u0906\u0922\u093c\u0924 \u0926\u0932\u093e\u0932", "margin_pct": 0.06, "cost_per_qtl": 55.0, "loss_pct": 0.015, "essential": false, "kind": "intermediary", "note": "APMC commission, mandi cess, unloading labour."}, {"key": "wholesaler", "label_en": "Wholesaler (mandi \u2192 city)", "label_mr": "\u0918\u093e\u090a\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0925\u094b\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.1, "cost_per_qtl": 130.0, "loss_pct": 0.03, "essential": false, "kind": "intermediary", "note": "Long-haul freight to the consumption centre plus price risk."}, {"key": "distributor", "label_en": "Distributor / sub-wholesaler", "label_mr": "\u0935\u093f\u0924\u0930\u0915", "label_hi": "\u0935\u093f\u0924\u0930\u0915", "margin_pct": 0.08, "cost_per_qtl": 80.0, "loss_pct": 0.025, "essential": false, "kind": "intermediary", "note": "Breaks bulk, delivers to retail outlets."}, {"key": "retailer", "label_en": "Retailer", "label_mr": "\u0915\u093f\u0930\u0915\u094b\u0933 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0916\u0941\u0926\u0930\u093e \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.18, "cost_per_qtl": 95.0, "loss_pct": 0.06, "essential": false, "kind": "retail", "note": "Shop rent, labour, packaging, unsold stock."}]'::jsonb,
     1.0, 'given',
     'Default vegetable chain shape from published value-chain studies; the '
     'level is calibrated per market at request time. Seeded by migration 041 '
     'so the table is no longer empty - edit these rows to retune without a '
     'deploy.',
     true),

    ('oilseed', '', 'traditional',
     '[{"key": "village_aggregator", "label_en": "Village trader / aggregator", "label_mr": "\u0917\u093e\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0917\u093e\u0901\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.05, "cost_per_qtl": 30.0, "loss_pct": 0.02, "essential": false, "kind": "assembly", "note": "Buys at the farm gate, assembles lots, extends credit."}, {"key": "commission_agent", "label_en": "Commission agent (arhatiya)", "label_mr": "\u0906\u0921\u0924 \u0926\u0932\u093e\u0932", "label_hi": "\u0906\u0922\u093c\u0924 \u0926\u0932\u093e\u0932", "margin_pct": 0.06, "cost_per_qtl": 45.0, "loss_pct": 0.015, "essential": false, "kind": "intermediary", "note": "APMC commission, mandi cess, unloading labour."}, {"key": "wholesaler", "label_en": "Wholesaler (mandi \u2192 city)", "label_mr": "\u0918\u093e\u090a\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0925\u094b\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.1, "cost_per_qtl": 110.0, "loss_pct": 0.03, "essential": false, "kind": "intermediary", "note": "Long-haul freight to the consumption centre plus price risk."}, {"key": "distributor", "label_en": "Distributor / sub-wholesaler", "label_mr": "\u0935\u093f\u0924\u0930\u0915", "label_hi": "\u0935\u093f\u0924\u0930\u0915", "margin_pct": 0.08, "cost_per_qtl": 70.0, "loss_pct": 0.025, "essential": false, "kind": "intermediary", "note": "Breaks bulk, delivers to retail outlets."}, {"key": "retailer", "label_en": "Retailer", "label_mr": "\u0915\u093f\u0930\u0915\u094b\u0933 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0916\u0941\u0926\u0930\u093e \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.18, "cost_per_qtl": 60.0, "loss_pct": 0.015, "essential": false, "kind": "retail", "note": "Shop rent, labour, packaging, unsold stock."}]'::jsonb,
     1.0, 'given',
     'Default oilseed chain shape; includes an essential processing stage. The '
     'level is calibrated per market at request time. Seeded by migration 041.',
     true),

    ('cereal', '', 'traditional',
     '[{"key": "village_aggregator", "label_en": "Village trader / aggregator", "label_mr": "\u0917\u093e\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0917\u093e\u0901\u0935 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.05, "cost_per_qtl": 28.0, "loss_pct": 0.02, "essential": false, "kind": "assembly", "note": "Buys at the farm gate, assembles lots, extends credit."}, {"key": "commission_agent", "label_en": "Commission agent (arhatiya)", "label_mr": "\u0906\u0921\u0924 \u0926\u0932\u093e\u0932", "label_hi": "\u0906\u0922\u093c\u0924 \u0926\u0932\u093e\u0932", "margin_pct": 0.06, "cost_per_qtl": 42.0, "loss_pct": 0.015, "essential": false, "kind": "intermediary", "note": "APMC commission, mandi cess, unloading labour."}, {"key": "wholesaler", "label_en": "Wholesaler (mandi \u2192 city)", "label_mr": "\u0918\u093e\u090a\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0925\u094b\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.1, "cost_per_qtl": 100.0, "loss_pct": 0.03, "essential": false, "kind": "intermediary", "note": "Long-haul freight to the consumption centre plus price risk."}, {"key": "distributor", "label_en": "Distributor / sub-wholesaler", "label_mr": "\u0935\u093f\u0924\u0930\u0915", "label_hi": "\u0935\u093f\u0924\u0930\u0915", "margin_pct": 0.08, "cost_per_qtl": 65.0, "loss_pct": 0.025, "essential": false, "kind": "intermediary", "note": "Breaks bulk, delivers to retail outlets."}, {"key": "retailer", "label_en": "Retailer", "label_mr": "\u0915\u093f\u0930\u0915\u094b\u0933 \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "label_hi": "\u0916\u0941\u0926\u0930\u093e \u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940", "margin_pct": 0.18, "cost_per_qtl": 55.0, "loss_pct": 0.01, "essential": false, "kind": "retail", "note": "Shop rent, labour, packaging, unsold stock."}]'::jsonb,
     1.0, 'given',
     'Default cereal chain shape; includes an essential milling stage. The '
     'level is calibrated per market at request time. Seeded by migration 041.',
     true)

on conflict (category, scope_district, channel,
             coalesce(commodity_id, '00000000-0000-0000-0000-000000000000'::uuid))
do update set
    stages            = excluded.stages,
    margin_scale      = excluded.margin_scale,
    calibration_status = excluded.calibration_status,
    source_note       = excluded.source_note,
    is_active         = excluded.is_active,
    calibrated_at     = now();

-- Fail loudly rather than silently: an empty table after this migration means
-- the engine's "retune from the DB" path has nothing to read and is still
-- running purely off DEFAULT_CHAIN_PROFILES.
do $$
declare
    n bigint;
begin
    select count(*) into n
      from public.value_chain_profiles
     where channel = 'traditional' and is_active;
    if n = 0 then
        raise exception 'migration 041 seeded no traditional chain profiles';
    end if;
    raise notice 'migration 041: % active traditional chain profile(s)', n;
end $$;

commit;
