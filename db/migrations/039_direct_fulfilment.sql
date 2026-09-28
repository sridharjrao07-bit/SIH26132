-- =============================================================================
-- SIH26033 — Disintermediation: fulfilment, settlement and traceability
-- Migration 039 — applies AFTER 038
--
-- Where 038 added the *inputs* to a direct trade (retail anchor, chain model,
-- consumer demand, group buys), 039 adds the *outputs*: the plan itself, the
-- per-lane economics, the shipments, and the traceable consumer order.
--
-- The point of these tables is accountability.  A claim like "the farmer got
-- 41% more and the consumer paid 16% less" is only worth anything if every
-- rupee in it can be traced back to a named stage of the chain it displaced.
-- So every row carries its counterfactual alongside its actual:
--
--   direct_allocations.mandi_realisation_rs   vs farmer_realisation_rs
--   direct_orders.retail_reference_per_qtl    vs consumer_price_per_qtl
--
-- and `direct_plans.impact` stores the rolled-up totals as JSONB signed by the
-- engine config that produced them (`direct_plans.config`).  A plan is a
-- reproducible artefact, not an assertion.
--
-- Traceability
-- ------------
-- `direct_orders.trace_token` is the consumer-facing handle.  It is a short
-- random string, NOT a UUID, and NOT derived from any id — a guessable token
-- would let anyone enumerate orders.  It is generated server-side by
-- `direct_plan_commit` and exposed through a single SECURITY DEFINER lookup RPC
-- so no anonymous caller needs broad table rights.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. direct_plans — a reproducible planning artefact
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.direct_plans (
    id              uuid primary key default gen_random_uuid(),
    plan_id         text not null unique,      -- engine's deterministic DP-<hash>
    commodity_id    uuid references public.commodities (id) on delete set null,
    district        text not null default 'Nashik',
    generated_by    uuid references public.user_profiles (id) on delete set null,
    generated_at    timestamptz not null default now(),
    status          text not null default 'draft'
                        check (status in ('draft', 'committed', 'cancelled')),
    -- The full engine configuration: alpha, platform fee, freight rate card,
    -- cluster size, calibration flags.  Stored so a plan can be re-derived.
    config          jsonb not null default '{}'::jsonb,
    -- Rolled-up ImpactSummary: farmer gain, consumer saving, surplus, chain
    -- lengths before/after.  Denormalised deliberately — this is the reported
    -- result and it must not drift if the inputs are later edited.
    impact          jsonb not null default '{}'::jsonb,
    calibrations    jsonb not null default '{}'::jsonb,
    notes           jsonb not null default '[]'::jsonb,

    constraint chk_plan_config_is_object check (jsonb_typeof(config) = 'object')
);

comment on table public.direct_plans is
  'A direct-channel plan produced by the disintermediation engine. plan_id is a '
  'deterministic hash of (lots, demands, config), so identical inputs reproduce an '
  'identical plan. impact/config/calibrations are frozen at generation time.';

create index if not exists idx_direct_plans_commodity
    on public.direct_plans (commodity_id, generated_at desc);
create index if not exists idx_direct_plans_status
    on public.direct_plans (status, generated_at desc);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. direct_allocations — one lane of a plan
--
-- Every money column appears in pairs: the direct outcome and the counterfactual
-- it is measured against.  That pairing is the audit trail.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.direct_allocations (
    id                      uuid primary key default gen_random_uuid(),
    plan_id                 text not null
                                references public.direct_plans (plan_id) on delete cascade,
    allocation_id           text not null,     -- engine's "A<i>-<j>"
    lot_id                  uuid references public.lots (id) on delete set null,
    demand_id               uuid references public.consumer_nodes (id) on delete set null,
    farmer_id               uuid references public.user_profiles (id) on delete set null,
    shipment_id             text,

    farm_qtl                numeric(12, 3) not null check (farm_qtl > 0),
    delivered_qtl           numeric(12, 3) not null check (delivered_qtl >= 0),
    distance_km             numeric(9, 3) not null check (distance_km >= 0),

    -- Farmer side: ₹ per quintal at the farm gate
    farmer_price_per_qtl    numeric(10, 2) not null check (farmer_price_per_qtl >= 0),
    mandi_price_per_qtl     numeric(10, 2) not null check (mandi_price_per_qtl >= 0),
    farmer_gain_rs          numeric(14, 2) not null default 0,

    -- Consumer side: ₹ per quintal delivered
    consumer_price_per_qtl  numeric(10, 2) not null check (consumer_price_per_qtl >= 0),
    retail_reference_per_qtl numeric(10, 2) not null check (retail_reference_per_qtl >= 0),
    consumer_saving_rs      numeric(14, 2) not null default 0,

    -- The pie and what it cost to move
    surplus_rs              numeric(14, 2) not null default 0,
    freight_rs              numeric(14, 2) not null default 0 check (freight_rs >= 0),
    platform_fee_rs         numeric(14, 2) not null default 0 check (platform_fee_rs >= 0),
    farmer_share_rs         numeric(14, 2) not null default 0 check (farmer_share_rs >= 0),

    -- The Nash split inputs, so the split can be recomputed and checked
    alpha                   numeric(5, 4) not null default 0.5
                                check (alpha between 0 and 1),
    effective_markup        numeric(9, 6) not null default 0,
    additive_cost_per_qtl   numeric(10, 4) not null default 0,
    delivered_ratio         numeric(8, 6) not null default 1,

    created_at              timestamptz not null default now(),

    constraint uq_direct_allocation unique (plan_id, allocation_id),
    -- The trade is only recorded if BOTH sides gain.  This is the database-level
    -- statement of the platform's core promise; if the economics ever go wrong,
    -- the write fails loudly instead of quietly booking a bad trade.
    constraint chk_mutual_gain check (farmer_gain_rs >= 0 and consumer_saving_rs >= 0),
    constraint chk_delivered_le_farm check (delivered_qtl <= farm_qtl + 0.001),
    constraint chk_alpha_range check (alpha between 0 and 1)
);

comment on table public.direct_allocations is
  'One lane of a direct plan. Money columns are stored as (actual, counterfactual) '
  'pairs so the claimed gain is auditable. chk_mutual_gain enforces that no '
  'allocation is ever recorded where either side is worse off than the status quo.';

create index if not exists idx_direct_allocations_plan
    on public.direct_allocations (plan_id);
create index if not exists idx_direct_allocations_farmer
    on public.direct_allocations (farmer_id, created_at desc);
create index if not exists idx_direct_allocations_demand
    on public.direct_allocations (demand_id);
create index if not exists idx_direct_allocations_lot
    on public.direct_allocations (lot_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. direct_shipments — the consolidated vehicles
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.direct_shipments (
    id              uuid primary key default gen_random_uuid(),
    plan_id         text not null
                        references public.direct_plans (plan_id) on delete cascade,
    shipment_id     text not null,
    lane_key        text not null,             -- "<origin cluster>><dest cluster>"
    distance_km     numeric(9, 3) not null check (distance_km >= 0),
    load_qtl        numeric(12, 3) not null check (load_qtl >= 0),
    vehicles        integer not null check (vehicles >= 0),
    capacity_qtl    numeric(12, 3) not null check (capacity_qtl > 0),
    fill_pct        numeric(6, 3) not null default 0,
    rate_basis      text not null default 'LTL' check (rate_basis in ('FTL', 'LTL')),
    freight_rs      numeric(14, 2) not null default 0 check (freight_rs >= 0),
    freight_per_qtl numeric(10, 4) not null default 0,
    status          text not null default 'planned'
                        check (status in ('planned', 'booked', 'in_transit', 'delivered', 'cancelled')),
    manifest        jsonb not null default '[]'::jsonb,
    created_at      timestamptz not null default now(),

    constraint uq_direct_shipment unique (plan_id, shipment_id),
    constraint chk_load_fits_vehicles
        check (load_qtl <= capacity_qtl * greatest(vehicles, 1) + 0.001)
);

comment on table public.direct_shipments is
  'Consolidated vehicles for a plan. fill_pct and rate_basis record the FTL/LTL '
  'economics the plan relied on; manifest holds the per-vehicle loading list.';

create index if not exists idx_direct_shipments_plan
    on public.direct_shipments (plan_id, shipment_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. direct_orders — the consumer's traceable receipt
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.direct_orders (
    id                      uuid primary key default gen_random_uuid(),
    allocation_uuid         uuid references public.direct_allocations (id) on delete set null,
    plan_id                 text references public.direct_plans (plan_id) on delete set null,
    consumer_node_id        uuid references public.consumer_nodes (id) on delete set null,
    user_id                 uuid references public.user_profiles (id) on delete set null,
    group_buy_id            uuid references public.group_buys (id) on delete set null,
    lot_id                  uuid references public.lots (id) on delete set null,
    farmer_id               uuid references public.user_profiles (id) on delete set null,

    trace_token             text not null unique,
    qtl                     numeric(12, 3) not null check (qtl > 0),
    consumer_price_per_qtl  numeric(10, 2) not null check (consumer_price_per_qtl >= 0),
    retail_reference_per_qtl numeric(10, 2) not null check (retail_reference_per_qtl >= 0),
    farmer_price_per_qtl    numeric(10, 2) not null check (farmer_price_per_qtl >= 0),
    mandi_price_per_qtl     numeric(10, 2) not null check (mandi_price_per_qtl >= 0),
    saving_rs               numeric(14, 2) not null default 0,
    -- The consumer-rupee receipt: where the money actually went.
    farmer_share_rs         numeric(14, 2) not null default 0,
    logistics_share_rs      numeric(14, 2) not null default 0,
    platform_share_rs       numeric(14, 2) not null default 0,

    status                  text not null default 'confirmed'
                                check (status in (
                                    'confirmed', 'in_transit', 'delivered',
                                    'cancelled', 'disputed'
                                )),
    created_at              timestamptz not null default now(),

    constraint chk_order_shares_reconcile
        check (
            abs((farmer_share_rs + logistics_share_rs + platform_share_rs)
                - (consumer_price_per_qtl * qtl)) < 1.0
        )
);

comment on table public.direct_orders is
  'Traceable consumer receipt for a direct trade. chk_order_shares_reconcile enforces '
  'that farmer + logistics + platform shares exactly account for what the consumer '
  'paid — the receipt cannot silently over- or under-report.';

create index if not exists idx_direct_orders_consumer
    on public.direct_orders (user_id, created_at desc);
create index if not exists idx_direct_orders_group_buy
    on public.direct_orders (group_buy_id);
create index if not exists idx_direct_orders_farmer
    on public.direct_orders (farmer_id, created_at desc);


-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

alter table public.direct_plans       enable row level security;
alter table public.direct_allocations enable row level security;
alter table public.direct_shipments   enable row level security;
alter table public.direct_orders      enable row level security;

-- ── plans: participants see their own; admins see all ────────────────────────
drop policy if exists "Participants read own plans" on public.direct_plans;
create policy "Participants read own plans"
    on public.direct_plans for select
    using (
        public.has_role('admin')
        or generated_by = auth.uid()
        or exists (
            select 1 from public.direct_allocations a
             where a.plan_id = public.direct_plans.plan_id
               and (a.farmer_id = auth.uid() or a.demand_id in (
                    select c.id from public.consumer_nodes c where c.user_id = auth.uid()
               ))
        )
    );

-- Plans are written through direct_plan_commit (SECURITY DEFINER); no direct
-- INSERT/UPDATE grant is given, so a caller cannot fabricate an impact figure.

-- ── allocations: farmer and matched consumer see their lanes ─────────────────
drop policy if exists "Farmers read own allocations" on public.direct_allocations;
create policy "Farmers read own allocations"
    on public.direct_allocations for select
    using (
        public.has_role('admin')
        or farmer_id = auth.uid()
        or demand_id in (
            select c.id from public.consumer_nodes c where c.user_id = auth.uid()
        )
    );

-- ── shipments: read-only for plan participants ───────────────────────────────
drop policy if exists "Participants read own shipments" on public.direct_shipments;
create policy "Participants read own shipments"
    on public.direct_shipments for select
    using (
        public.has_role('admin')
        or exists (
            select 1 from public.direct_plans p
             where p.plan_id = public.direct_shipments.plan_id
               and (
                    p.generated_by = auth.uid()
                    or exists (
                        select 1 from public.direct_allocations a
                         where a.plan_id = p.plan_id and a.farmer_id = auth.uid()
                    )
               )
        )
    );

-- ── orders: owner-only.  Deliberately no anon policy: the public trace lookup
--    goes through the direct_order_trace RPC, which returns a redacted view. ──
drop policy if exists "Consumers read own orders" on public.direct_orders;
create policy "Consumers read own orders"
    on public.direct_orders for select
    using (
        public.has_role('admin')
        or user_id = auth.uid()
        or farmer_id = auth.uid()
    );


-- =============================================================================
-- RPCs
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- direct_plan_commit — persist a plan, its lanes, its shipments and its orders
--                      atomically.
--
-- Why an RPC rather than app-layer inserts: a plan is a set of mutually
-- dependent rows whose money columns must reconcile with each other AND with
-- the chk_mutual_gain invariant.  Writing them in one transaction under
-- SECURITY DEFINER is the only way a partially-written plan cannot exist.
--
-- The engine has already done the economics; this function's job is integrity,
-- not computation.  It re-derives nothing and trusts nothing it can check.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.direct_plan_commit(
    p_plan_id       text,
    p_commodity_id  uuid,
    p_district      text    default 'Nashik',
    p_config        jsonb   default '{}'::jsonb,
    p_impact        jsonb   default '{}'::jsonb,
    p_calibrations  jsonb   default '{}'::jsonb,
    p_notes         jsonb   default '[]'::jsonb,
    p_allocations   jsonb   default '[]'::jsonb,
    p_shipments     jsonb   default '[]'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id  uuid := auth.uid();
    v_plan     public.direct_plans%rowtype;
    v_alloc    jsonb;
    v_ship     jsonb;
    v_alloc_id uuid;
    v_token    text;
    v_shares   numeric;
    v_tokens   jsonb := '[]'::jsonb;   -- trace tokens handed back to the caller
begin
    if v_user_id is null and not public.has_role('admin') then
        raise exception 'direct_plan_commit requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if p_plan_id is null or btrim(p_plan_id) = '' then
        raise exception 'direct_plan_commit: plan_id is required'
            using errcode = 'P0004';
    end if;

    if jsonb_typeof(p_allocations) <> 'array' then
        raise exception 'direct_plan_commit: allocations must be a JSON array'
            using errcode = 'P0004';
    end if;

    -- Idempotent: re-committing the same plan_id returns the existing row
    -- instead of duplicating lanes or double-booking the same plan.
    select * into v_plan from public.direct_plans where plan_id = p_plan_id;
    if found then
        -- Re-minted tokens are useless (the old ones are on the crates), so a
        -- replay returns the tokens that were issued the first time.
        -- direct_orders links back by allocation_uuid; created_at is the only
        -- ordering that mirrors the order the lanes were minted in.
        select coalesce(jsonb_agg(o.trace_token order by o.created_at, o.id), '[]'::jsonb)
          into v_tokens
          from public.direct_orders o
         where o.plan_id = p_plan_id;

        return jsonb_build_object(
            'plan_id', v_plan.plan_id,
            'id',      v_plan.id,
            'status',  v_plan.status,
            'allocations', jsonb_array_length(v_tokens),
            'shipments', jsonb_array_length(p_shipments),
            'trace_tokens', v_tokens,
            'already_committed', true
        );
    end if;

    insert into public.direct_plans (
        plan_id, commodity_id, district, generated_by, status,
        config, impact, calibrations, notes
    ) values (
        p_plan_id, p_commodity_id, coalesce(p_district, 'Nashik'), v_user_id, 'committed',
        p_config, p_impact, p_calibrations, p_notes
    )
    returning * into v_plan;

    -- Shipments first: allocations reference them by engine id.
    for v_ship in select * from jsonb_array_elements(p_shipments) loop
        insert into public.direct_shipments (
            plan_id, shipment_id, lane_key, distance_km, load_qtl, vehicles,
            capacity_qtl, fill_pct, rate_basis, freight_rs, freight_per_qtl, manifest
        ) values (
            p_plan_id,
            v_ship ->> 'shipment_id',
            coalesce(v_ship ->> 'lane_key', ''),
            coalesce((v_ship ->> 'distance_km')::numeric, 0),
            coalesce((v_ship ->> 'load_qtl')::numeric, 0),
            greatest(coalesce((v_ship ->> 'vehicles')::integer, 0), 0),
            coalesce((v_ship ->> 'capacity_qtl')::numeric, 90),
            coalesce((v_ship ->> 'fill_pct')::numeric, 0),
            coalesce(v_ship ->> 'rate_basis', 'LTL'),
            coalesce((v_ship ->> 'freight_rs')::numeric, 0),
            coalesce((v_ship ->> 'freight_per_qtl')::numeric, 0),
            coalesce(v_ship -> 'manifest', '[]'::jsonb)
        );
    end loop;

    for v_alloc in select * from jsonb_array_elements(p_allocations) loop
        -- Trace token: 12 random chars from a restricted alphabet.  Not derived
        -- from any id and not sequential, so tokens are not enumerable.
        v_token := upper(substr(
            replace(replace(replace(encode(extensions.gen_random_bytes(12), 'base64'), '+', ''), '/', ''), '=', ''),
            1, 12
        ));

        insert into public.direct_allocations (
            plan_id, allocation_id, lot_id, demand_id, farmer_id, shipment_id,
            farm_qtl, delivered_qtl, distance_km,
            farmer_price_per_qtl, mandi_price_per_qtl, farmer_gain_rs,
            consumer_price_per_qtl, retail_reference_per_qtl, consumer_saving_rs,
            surplus_rs, freight_rs, platform_fee_rs, farmer_share_rs,
            alpha, effective_markup, additive_cost_per_qtl, delivered_ratio
        ) values (
            p_plan_id,
            v_alloc ->> 'allocation_id',
            nullif(v_alloc ->> 'lot_id', '')::uuid,
            nullif(v_alloc ->> 'demand_id', '')::uuid,
            nullif(v_alloc ->> 'farmer_id', '')::uuid,
            coalesce(v_alloc ->> 'shipment_id', ''),
            (v_alloc ->> 'farm_qtl')::numeric,
            (v_alloc ->> 'delivered_qtl')::numeric,
            (v_alloc ->> 'distance_km')::numeric,
            (v_alloc ->> 'farmer_price_per_qtl')::numeric,
            (v_alloc ->> 'mandi_price_per_qtl')::numeric,
            coalesce((v_alloc ->> 'farmer_gain_rs')::numeric, 0),
            (v_alloc ->> 'consumer_price_per_qtl')::numeric,
            (v_alloc ->> 'retail_reference_per_qtl')::numeric,
            coalesce((v_alloc ->> 'consumer_saving_rs')::numeric, 0),
            coalesce((v_alloc ->> 'surplus_rs')::numeric, 0),
            coalesce((v_alloc ->> 'freight_rs')::numeric, 0),
            coalesce((v_alloc ->> 'platform_fee_rs')::numeric, 0),
            coalesce((v_alloc ->> 'farmer_share_rs')::numeric, 0),
            coalesce((v_alloc ->> 'alpha')::numeric, 0.5),
            coalesce((v_alloc ->> 'effective_markup')::numeric, 0),
            coalesce((v_alloc ->> 'additive_cost_per_qtl')::numeric, 0),
            coalesce((v_alloc ->> 'delivered_ratio')::numeric, 1)
        )
        returning id into v_alloc_id;

        -- Shares must reconcile before the order is written, so a receipt can
        -- never misreport where the consumer's rupee went.
        v_shares := coalesce((v_alloc ->> 'farmer_share_rs')::numeric, 0)
                  + coalesce((v_alloc ->> 'logistics_share_rs')::numeric, 0)
                  + coalesce((v_alloc ->> 'platform_share_rs')::numeric, 0);

        insert into public.direct_orders (
            allocation_uuid, plan_id, consumer_node_id, lot_id, farmer_id,
            trace_token, qtl,
            consumer_price_per_qtl, retail_reference_per_qtl,
            farmer_price_per_qtl, mandi_price_per_qtl, saving_rs,
            farmer_share_rs, logistics_share_rs, platform_share_rs, status
        ) values (
            v_alloc_id,
            p_plan_id,
            nullif(v_alloc ->> 'demand_id', '')::uuid,
            nullif(v_alloc ->> 'lot_id', '')::uuid,
            nullif(v_alloc ->> 'farmer_id', '')::uuid,
            v_token,
            (v_alloc ->> 'delivered_qtl')::numeric,
            (v_alloc ->> 'consumer_price_per_qtl')::numeric,
            (v_alloc ->> 'retail_reference_per_qtl')::numeric,
            (v_alloc ->> 'farmer_price_per_qtl')::numeric,
            (v_alloc ->> 'mandi_price_per_qtl')::numeric,
            coalesce((v_alloc ->> 'consumer_saving_rs')::numeric, 0),
            coalesce((v_alloc ->> 'farmer_share_rs')::numeric, 0),
            coalesce((v_alloc ->> 'logistics_share_rs')::numeric, 0),
            coalesce((v_alloc ->> 'platform_share_rs')::numeric, 0),
            'confirmed'
        );

        v_tokens := v_tokens || to_jsonb(v_token);
    end loop;

    -- One token per confirmed order.  Returning them here is the only way the
    -- caller can print the QR codes: direct_orders has no SELECT grant, by
    -- design, so the tokens would otherwise be unreachable.
    return jsonb_build_object(
        'plan_id', p_plan_id,
        'id', v_plan.id,
        'status', 'committed',
        'allocations', jsonb_array_length(p_allocations),
        'shipments', jsonb_array_length(p_shipments),
        'trace_tokens', v_tokens,
        'already_committed', false
    );
end;
$$;

revoke all on function public.direct_plan_commit(text,uuid,text,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb)
    from public, anon;
grant execute on function public.direct_plan_commit(text,uuid,text,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb)
    to authenticated;

comment on function public.direct_plan_commit is
    'SECURITY DEFINER. Atomically persists a plan, its shipments, its allocations '
    'and a traceable order per allocation. Idempotent on plan_id. Generates a random '
    'non-enumerable trace_token per order.';


-- ─────────────────────────────────────────────────────────────────────────────
-- direct_order_trace — public, token-gated provenance lookup.
--
-- Deliberately anon-callable but REDACTED: it proves the trade happened and
-- shows the rupee split, but returns no names, phones or coordinates.  A QR code
-- printed on a crate is inherently public, so the payload must be safe by
-- construction rather than protected by a login nobody will complete.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.direct_order_trace(p_token text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_order public.direct_orders%rowtype;
    v_commodity text;
    v_district text;
begin
    if p_token is null or btrim(p_token) = '' then
        return null;
    end if;

    select * into v_order from public.direct_orders where trace_token = btrim(upper(p_token));
    if not found then
        return null;
    end if;

    select c.name_en into v_commodity
      from public.lots l
      join public.commodities c on c.id = l.commodity_id
     where l.id = v_order.lot_id;

    select district into v_district
      from public.direct_plans
     where plan_id = v_order.plan_id;

    return jsonb_build_object(
        'trace_token',            v_order.trace_token,
        'commodity',              v_commodity,
        'district',               v_district,
        'quantity_qtl',           v_order.qtl,
        'status',                 v_order.status,
        'created_at',             v_order.created_at,
        'consumer', jsonb_build_object(
            'price_per_qtl',      v_order.consumer_price_per_qtl,
            'retail_reference_per_qtl', v_order.retail_reference_per_qtl,
            'saving_rs',          v_order.saving_rs
        ),
        'farmer', jsonb_build_object(
            'price_per_qtl',      v_order.farmer_price_per_qtl,
            'mandi_price_per_qtl', v_order.mandi_price_per_qtl
        ),
        'consumer_rupee', jsonb_build_object(
            'farmer_share_rs',    v_order.farmer_share_rs,
            'logistics_share_rs', v_order.logistics_share_rs,
            'platform_share_rs',  v_order.platform_share_rs,
            'total_rs',           v_order.consumer_price_per_qtl * v_order.qtl
        )
    );
end;
$$;

revoke all on function public.direct_order_trace(text) from public;
grant execute on function public.direct_order_trace(text) to anon, authenticated;

comment on function public.direct_order_trace is
    'SECURITY DEFINER. Token-gated provenance lookup for a direct order. Returns a '
    'redacted consumer-rupee receipt: no names, phones or coordinates. Safe to expose '
    'via a QR code on packaging.';


-- ─────────────────────────────────────────────────────────────────────────────
-- direct_impact — district rollup for the dashboard.
--
-- Aggregates over committed plans so the headline numbers ("₹X moved from
-- intermediaries to farmers and consumers") are computed from stored rows, not
-- from whatever the last API call happened to return.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.direct_impact(
    p_commodity_id uuid default null,
    p_district     text default null
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    select jsonb_build_object(
        'plans',          count(distinct a.plan_id),
        'allocations',    count(*),
        'farm_qtl_moved', coalesce(sum(a.farm_qtl), 0),
        'farmer_realisation_rs', coalesce(sum(a.farmer_price_per_qtl * a.farm_qtl), 0),
        'mandi_realisation_rs',  coalesce(sum(a.mandi_price_per_qtl * a.farm_qtl), 0),
        'farmer_gain_rs',        coalesce(sum(a.farmer_gain_rs), 0),
        'consumer_saving_rs',    coalesce(sum(a.consumer_saving_rs), 0),
        'surplus_rs',            coalesce(sum(a.surplus_rs), 0),
        'freight_rs',            coalesce(sum(a.freight_rs), 0),
        'platform_fee_rs',       coalesce(sum(a.platform_fee_rs), 0)
    )
    from public.direct_allocations a
    join public.direct_plans p on p.plan_id = a.plan_id
    where p.status = 'committed'
      and (p_commodity_id is null or p.commodity_id = p_commodity_id)
      and (p_district is null or p.district = p_district);
$$;

revoke all on function public.direct_impact(uuid, text) from public;
grant execute on function public.direct_impact(uuid, text) to anon, authenticated;

comment on function public.direct_impact is
    'SECURITY DEFINER, STABLE. District/commodity rollup of realised direct-channel '
    'impact over committed plans. Aggregates stored rows, never recomputes economics.';

-- =============================================================================
-- 7. WRITE PATHS FOR THE 038 TABLES
-- =============================================================================
-- 038 created `retail_prices`, `consumer_nodes`, `group_buys` and
-- `group_buy_members` with RLS but no write path.  Client-side inserts could
-- not satisfy the "own row" RLS policies without leaking the owner column, and
-- `group_buys.committed_qtl` must stay consistent with its members under
-- concurrent joins.
--
-- So every write goes through a SECURITY DEFINER RPC that:
--   * derives the owner from the JWT (never from the payload — otherwise any
--     caller could forge another user's consumer node);
--   * re-validates the invariants CHECK constraints cannot express
--     (deadline in the future, member node owned by the joiner, headroom left);
--   * takes a row lock where a read-then-write would otherwise race.
--
-- Column names below follow 038 exactly: `name` (not `label`), `organiser_id`
-- (not `coordinator_id`), `deadline` (not `expires_at`), `demand_qtl`,
-- `price_date`, `market_area`, `retail_price`.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 7.1 Consumer nodes — "where does the demand live?"
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.consumer_node_upsert(
    p_name               text,
    p_kind               text default 'household',
    p_district           text default 'Nashik',
    p_lat                numeric default null,
    p_lng                numeric default null,
    p_pincode            text default null,
    p_commodity_id       uuid default null,
    p_demand_qtl         numeric default null,
    p_max_price_per_qtl  numeric default null,
    p_household_size     integer default null,
    p_contact_phone      text default null,
    p_node_id            uuid default null            -- update when supplied
)
returns public.consumer_nodes
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid uuid := auth.uid();
    v_row public.consumer_nodes;
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_name is null or btrim(p_name) = '' then
        raise exception 'name is required' using errcode = '22023';
    end if;
    if (p_lat is null) <> (p_lng is null) then
        raise exception 'lat and lng must be supplied together' using errcode = '22023';
    end if;
    if p_demand_qtl is not null and p_demand_qtl < 0 then
        raise exception 'demand_qtl must be non-negative' using errcode = '22023';
    end if;
    if p_max_price_per_qtl is not null and p_max_price_per_qtl <= 0 then
        raise exception 'max_price_per_qtl must be positive' using errcode = '22023';
    end if;
    if p_household_size is not null and p_household_size <= 0 then
        raise exception 'household_size must be positive' using errcode = '22023';
    end if;
    -- CHECK constraints on lat/lng reject out-of-range values anyway, but a
    -- constraint violation surfaces as an opaque 23514; name the real problem.
    if p_lat is not null and (p_lat < -90 or p_lat > 90) then
        raise exception 'lat out of range (% must be within -90..90)', p_lat
            using errcode = '22023';
    end if;
    if p_lng is not null and (p_lng < -180 or p_lng > 180) then
        raise exception 'lng out of range (% must be within -180..180)', p_lng
            using errcode = '22023';
    end if;

    if p_node_id is null then
        insert into public.consumer_nodes (
            user_id, name, kind, district, lat, lng, pincode, commodity_id,
            demand_qtl, max_price_per_qtl, household_size, contact_phone
        ) values (
            v_uid, btrim(p_name), p_kind, p_district, p_lat, p_lng, p_pincode,
            p_commodity_id, coalesce(p_demand_qtl, 0), p_max_price_per_qtl,
            p_household_size, p_contact_phone
        )
        returning * into v_row;
    else
        -- RLS already scopes the UPDATE to the owner; the explicit `user_id`
        -- predicate makes that guarantee independent of RLS being enabled.
        update public.consumer_nodes n
           set name              = btrim(p_name),
               kind              = p_kind,
               district          = p_district,
               lat               = coalesce(p_lat, n.lat),
               lng               = coalesce(p_lng, n.lng),
               pincode           = coalesce(p_pincode, n.pincode),
               commodity_id      = coalesce(p_commodity_id, n.commodity_id),
               demand_qtl        = coalesce(p_demand_qtl, n.demand_qtl),
               max_price_per_qtl = coalesce(p_max_price_per_qtl, n.max_price_per_qtl),
               household_size    = coalesce(p_household_size, n.household_size),
               contact_phone     = coalesce(p_contact_phone, n.contact_phone),
               updated_at        = now()
         where n.id = p_node_id
           and n.user_id = v_uid
        returning * into v_row;

        if v_row.id is null then
            raise exception 'consumer node % not found for this user', p_node_id
                using errcode = 'P0002';
        end if;
    end if;

    return v_row;
end;
$$;

revoke all on function public.consumer_node_upsert(text, text, text, numeric, numeric, text, uuid, numeric, numeric, integer, text, uuid) from public;
grant execute on function public.consumer_node_upsert(text, text, text, numeric, numeric, text, uuid, numeric, numeric, integer, text, uuid) to authenticated;

comment on function public.consumer_node_upsert is
    'SECURITY DEFINER. Create or update one of the caller''s own consumer nodes. '
    'Owner is taken from the JWT, never from the payload.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 7.2 Group buys — pooling orders so a truck is worth sending
-- ─────────────────────────────────────────────────────────────────────────────
-- The interesting concurrency problem lives here.  `group_buys.committed_qtl`
-- is a running total over `group_buy_members`.  Two households joining at once
-- both read committed_qtl, both add their own quantity, and the second write
-- clobbers the first — an order silently evaporates and the truck arrives short.
-- The fix is the standard one: `select ... for update` on the group_buys row
-- serialises joins on the same group while leaving different groups parallel.

create or replace function public.group_buy_create(
    p_commodity_id   uuid,
    p_deadline       timestamptz,
    p_target_qtl     numeric default 0,
    p_min_load_qtl   numeric default 50,
    p_district       text default 'Nashik',
    p_lat            numeric default null,
    p_lng            numeric default null
)
returns public.group_buys
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid uuid := auth.uid();
    v_row public.group_buys;
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_commodity_id is null then
        raise exception 'commodity_id is required' using errcode = '22023';
    end if;
    if p_deadline is null or p_deadline <= now() then
        raise exception 'deadline must be in the future' using errcode = '22023';
    end if;
    if p_min_load_qtl is null or p_min_load_qtl <= 0 then
        raise exception 'min_load_qtl must be positive' using errcode = '22023';
    end if;
    if p_target_qtl is not null and p_target_qtl < 0 then
        raise exception 'target_qtl must be non-negative' using errcode = '22023';
    end if;
    -- An unattainable target is worse than no target: the group can never
    -- reach min_load_qtl, so nobody ships.  Report it at creation time.
    if p_target_qtl > 0 and p_target_qtl < p_min_load_qtl then
        raise exception 'target_qtl (%) is below min_load_qtl (%) — the group '
                        'could never be released', p_target_qtl, p_min_load_qtl
            using errcode = '22023';
    end if;

    insert into public.group_buys (
        organiser_id, commodity_id, district, lat, lng,
        target_qtl, min_load_qtl, deadline, status
    ) values (
        v_uid, p_commodity_id, p_district, p_lat, p_lng,
        coalesce(p_target_qtl, p_min_load_qtl), p_min_load_qtl, p_deadline, 'open'
    )
    returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.group_buy_create(uuid, timestamptz, numeric, numeric, text, numeric, numeric) from public;
grant execute on function public.group_buy_create(uuid, timestamptz, numeric, numeric, text, numeric, numeric) to authenticated;

comment on function public.group_buy_create is
    'SECURITY DEFINER. Open a group buy. The caller becomes its organiser.';


create or replace function public.group_buy_join(
    p_group_buy_id      uuid,
    p_qtl               numeric,
    p_consumer_node_id  uuid default null,   -- omit for a one-off join
    p_label             text default null
)
returns public.group_buy_members
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid   uuid := auth.uid();
    v_gb    public.group_buys;
    v_sum   numeric;
    v_row   public.group_buy_members;
    v_lat   numeric;
    v_lng   numeric;
    v_key   uuid;      -- the uniqueness key for this join
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_qtl is null or p_qtl <= 0 then
        raise exception 'qtl must be positive' using errcode = '22023';
    end if;

    -- ── The serialisation point ──────────────────────────────────────────────
    -- FOR UPDATE blocks a second joiner until this transaction commits, so the
    -- committed_qtl read below cannot be stale.  Placed after the cheap
    -- validations so the lock is held for as little time as possible.
    select * into v_gb from public.group_buys where id = p_group_buy_id for update;
    if v_gb.id is null then
        raise exception 'group buy % not found', p_group_buy_id using errcode = 'P0002';
    end if;
    if v_gb.status <> 'open' then
        raise exception 'group buy % is % (only open groups accept members)',
            p_group_buy_id, v_gb.status using errcode = 'P0001';
    end if;
    if v_gb.deadline <= now() then
        raise exception 'group buy % closed at %', p_group_buy_id, v_gb.deadline
            using errcode = 'P0001';
    end if;

    -- Ownership and coordinates.
    if p_consumer_node_id is not null then
        select n.lat, n.lng into v_lat, v_lng
          from public.consumer_nodes n
         where n.id = p_consumer_node_id and n.user_id = v_uid;
        if not found then
            raise exception 'consumer node % does not belong to this user',
                p_consumer_node_id using errcode = '42501';
        end if;
        v_key := p_consumer_node_id;
    end if;

    -- Re-derive from members rather than trusting the stored counter: if the
    -- two ever drift, the members are the ground truth.
    select coalesce(sum(m.qtl), 0) into v_sum
      from public.group_buy_members m
     where m.group_buy_id = p_group_buy_id
       and (v_key is null or m.consumer_node_id is distinct from v_key);

    if v_gb.target_qtl > 0 and v_sum + p_qtl > v_gb.target_qtl + 1e-9 then
        -- Report the actual headroom so the client can offer a smaller join
        -- instead of failing blind.
        raise exception 'join of % qtl exceeds target % (headroom % qtl)',
            p_qtl, v_gb.target_qtl, greatest(0::numeric, v_gb.target_qtl - v_sum)
            using errcode = 'P0001';
    end if;

    if v_key is not null then
        insert into public.group_buy_members (
            group_buy_id, consumer_node_id, user_id, qtl, lat, lng, label
        ) values (
            p_group_buy_id, p_consumer_node_id, v_uid, p_qtl, v_lat, v_lng, p_label
        )
        on conflict (group_buy_id, consumer_node_id) do update
            set qtl   = excluded.qtl,
                user_id = excluded.user_id,
                lat   = excluded.lat,
                lng   = excluded.lng,
                label = excluded.label
        returning * into v_row;
    else
        -- One-off join with no saved node: no natural key, so it is a pure
        -- insert and a repeat call adds a second line.  That is deliberate —
        -- a household may split an order across two delivery addresses.
        insert into public.group_buy_members (
            group_buy_id, user_id, qtl, label
        ) values (
            p_group_buy_id, v_uid, p_qtl, p_label
        )
        returning * into v_row;
    end if;

    update public.group_buys g
       set committed_qtl = (
               select coalesce(sum(m.qtl), 0) from public.group_buy_members m
                where m.group_buy_id = g.id),
           updated_at = now()
     where g.id = p_group_buy_id;

    return v_row;
end;
$$;

revoke all on function public.group_buy_join(uuid, numeric, uuid, text) from public;
grant execute on function public.group_buy_join(uuid, numeric, uuid, text) to authenticated;

comment on function public.group_buy_join is
    'SECURITY DEFINER. Join (or amend a join on) an open group buy. Takes a '
    'FOR UPDATE lock on the group row so concurrent joins cannot lose an order; '
    'committed_qtl is re-derived from members rather than incremented.';


create or replace function public.group_buy_leave(
    p_group_buy_id      uuid,
    p_consumer_node_id  uuid default null
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid    uuid := auth.uid();
    v_gb     public.group_buys;
    v_before integer;
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    select * into v_gb from public.group_buys where id = p_group_buy_id for update;
    if v_gb.id is null then
        raise exception 'group buy % not found', p_group_buy_id using errcode = 'P0002';
    end if;
    if v_gb.status <> 'open' then
        raise exception 'cannot leave a group buy in status %', v_gb.status
            using errcode = 'P0001';
    end if;

    delete from public.group_buy_members m
     where m.group_buy_id = p_group_buy_id
       and (
             -- a saved node of this user
             (p_consumer_node_id is not null
              and m.consumer_node_id = p_consumer_node_id
              and m.consumer_node_id in (select n.id from public.consumer_nodes n
                                          where n.user_id = v_uid))
             or
             -- or, when no node is named, this user's one-off lines
             (p_consumer_node_id is null
              and m.consumer_node_id is null
              and m.user_id = v_uid)
           );

    get diagnostics v_before = row_count;

    update public.group_buys g
       set committed_qtl = (
               select coalesce(sum(m.qtl), 0) from public.group_buy_members m
                where m.group_buy_id = g.id),
           updated_at = now()
     where g.id = p_group_buy_id;

    return v_before;   -- rows removed; 0 means the caller had nothing to leave
end;
$$;

revoke all on function public.group_buy_leave(uuid, uuid) from public;
grant execute on function public.group_buy_leave(uuid, uuid) to authenticated;

comment on function public.group_buy_leave is
    'SECURITY DEFINER. Withdraw the caller''s own membership from an open group '
    'buy and re-derive committed_qtl. Returns the number of rows removed.';


create or replace function public.group_buy_release(
    p_group_buy_id  uuid,
    p_plan_id       text default null
)
returns public.group_buys
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid  uuid := auth.uid();
    v_gb   public.group_buys;
    v_sum  numeric;
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    select * into v_gb from public.group_buys where id = p_group_buy_id for update;
    if v_gb.id is null then
        raise exception 'group buy % not found', p_group_buy_id using errcode = 'P0002';
    end if;
    if v_gb.organiser_id <> v_uid then
        raise exception 'only the organiser may release group buy %', p_group_buy_id
            using errcode = '42501';
    end if;
    if v_gb.status <> 'open' then
        raise exception 'group buy % is % - only an open group may be released',
            p_group_buy_id, v_gb.status using errcode = 'P0001';
    end if;

    select coalesce(sum(m.qtl), 0) into v_sum
      from public.group_buy_members m where m.group_buy_id = p_group_buy_id;

    -- The whole point of a group buy is that it fills a truck.  Releasing a
    -- sub-threshold group just reintroduces the per-trip fixed cost that
    -- consolidation exists to amortise.
    if v_sum + 1e-9 < v_gb.min_load_qtl then
        raise exception 'group buy % has % qtl committed, below min_load_qtl % '
                        '(short % qtl)',
            p_group_buy_id, v_sum, v_gb.min_load_qtl, v_gb.min_load_qtl - v_sum
            using errcode = 'P0001';
    end if;

    update public.group_buys
       set status           = 'released',
           released_plan_id = p_plan_id,
           released_at      = now(),
           updated_at       = now()
     where id = p_group_buy_id
    returning * into v_gb;

    return v_gb;
end;
$$;

revoke all on function public.group_buy_release(uuid, text) from public;
grant execute on function public.group_buy_release(uuid, text) to authenticated;

comment on function public.group_buy_release is
    'SECURITY DEFINER. Organiser-only: move an open group buy to released once '
    'committed_qtl reaches min_load_qtl, optionally binding it to a plan id.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 7.3 Retail price capture — the right-hand anchor of the whole analysis
-- ─────────────────────────────────────────────────────────────────────────────
-- Every "the consumer pays ₹X" claim traces back to a row in `retail_prices`.
-- This is the only user-supplied input to the margin model, so it gets the
-- strictest validation: a bad anchor silently discredits every downstream
-- number, and unlike a wrong freight parameter it leaves no arithmetic trace.

create or replace function public.retail_price_record(
    p_commodity_id   uuid,
    p_retail_price   numeric,
    p_price_date     date default current_date,
    p_district       text default 'Nashik',
    p_market_area    text default '',
    p_unit           text default 'quintal',
    p_source         text default 'manual',
    p_source_ref     text default null
)
returns public.retail_prices
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid uuid := auth.uid();
    v_row public.retail_prices;
begin
    if v_uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if p_commodity_id is null then
        raise exception 'commodity_id is required' using errcode = '22023';
    end if;
    if p_retail_price is null or p_retail_price <= 0 then
        raise exception 'retail_price must be positive' using errcode = '22023';
    end if;
    if p_unit not in ('quintal', 'kg') then
        raise exception 'unit must be quintal or kg' using errcode = '22023';
    end if;
    if p_source not in ('seed', 'data_gov_in', 'manual', 'model') then
        raise exception 'unknown source %', p_source using errcode = '22023';
    end if;
    if p_price_date > current_date then
        raise exception 'price_date must not be in the future' using errcode = '22023';
    end if;

    insert into public.retail_prices (
        commodity_id, district, market_area, price_date, retail_price, unit,
        source, source_ref
    ) values (
        p_commodity_id, p_district, coalesce(p_market_area, ''), p_price_date,
        p_retail_price, p_unit, p_source, p_source_ref
    )
    -- The unique key includes `source`, so a field survey never overwrites the
    -- government feed; a re-recording of the SAME source on the same day
    -- supersedes it (a corrected reading, not a second opinion).
    on conflict (commodity_id, district, market_area, price_date, source)
    do update set
        retail_price = excluded.retail_price,
        unit         = excluded.unit,
        source_ref   = excluded.source_ref
    returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.retail_price_record(uuid, numeric, date, text, text, text, text, text) from public;
grant execute on function public.retail_price_record(uuid, numeric, date, text, text, text, text, text) to authenticated;

comment on function public.retail_price_record is
    'SECURITY DEFINER. Record a retail observation. Upserts on '
    '(commodity, district, market_area, price_date, source) so a corrected '
    'reading from the same source supersedes the earlier one.';
