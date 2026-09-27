-- =============================================================================
-- SIH26033 — Disintermediation: the direct-channel spine
-- Migration 038 — applies AFTER 037
--
-- Problem statement: "Multiple intermediaries reduce farmers earnings and
-- increase consumer prices."
--
-- The existing schema (001–037) models the *mandi* side of the market: wholesale
-- prices, farmer lots, verified buyers, offers, payments.  It has no concept of
-- the CONSUMER, and no concept of the CHAIN that sits between the two.  Three
-- tables are needed before any direct trade can be priced:
--
--   retail_prices       what the consumer actually pays (the right-hand anchor).
--                       Without it the whole "consumer rupee" analysis is
--                       unanchored arithmetic.
--   value_chain_profiles
--                       the per-commodity chain model (stage margins, losses,
--                       handling costs) plus the calibrated margin scale.  Held
--                       in the database, not in code, so a district officer can
--                       retune the model without a deploy.
--   consumer_nodes      the demand side of a direct trade: households, RWAs,
--                       hostels, canteens, hotels, institutions, retailers.
--
-- Plus the group-buy tables, because a single household order cannot fill a
-- truck and consolidation is what makes direct delivery economic at all.
--
-- Design notes
-- ------------
-- * Every rupee amount is ₹ per QUINTAL, matching `prices.modal_price`.  Mixing
--   per-kg and per-quintal in one schema is the single most common source of
--   100x bugs in agri systems, so the unit is asserted in a CHECK where a sane
--   band exists and documented in a COMMENT everywhere else.
-- * `retail_prices` carries a `source` column and a UNIQUE constraint on
--   (commodity, geography, date, source) so re-ingestion is idempotent — the
--   same discipline already applied to `prices` in 001.
-- * Chain profiles are versioned by `is_active` rather than updated in place, so
--   a plan generated last week can still explain itself against the profile it
--   was calibrated with.
--
-- All statements are idempotent.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. retail_prices — the consumer-side anchor
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.retail_prices (
    id              uuid primary key default gen_random_uuid(),
    commodity_id    uuid not null references public.commodities (id) on delete restrict,
    district        text not null default 'Nashik',
    market_area     text not null default '',   -- e.g. 'Nashik city'; blank = district-wide
    price_date      date not null,
    retail_price    numeric(10, 2) not null check (retail_price > 0),
    unit            text not null default 'quintal'
                        check (unit in ('quintal', 'kg')),
    source          text not null,   -- 'seed' | 'data_gov_in' | 'manual' | 'model'
    source_ref      text,
    raw_payload     jsonb,
    created_at      timestamptz not null default now(),

    constraint uq_retail_price_record
        unique (commodity_id, district, market_area, price_date, source),
    constraint chk_retail_price_band check (retail_price between 1 and 1000000)
);

comment on table public.retail_prices is
  'Consumer (retail) price anchor, Rs/quintal. Paired with prices.modal_price this '
  'bounds the total value absorbed by the intermediary chain. Idempotent on re-ingest.';

create index if not exists idx_retail_prices_commodity_date
    on public.retail_prices (commodity_id, price_date desc);
create index if not exists idx_retail_prices_district_date
    on public.retail_prices (district, price_date desc);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. value_chain_profiles — the chain model, in data not code
--
-- `stages` is an ordered JSON array of stage objects:
--   { key, label_en, label_mr, label_hi, margin_pct, cost_per_qtl,
--     loss_pct, essential, kind, note }
--
-- The engine composes them into a single affine map (p_out = A·p_in + B), which
-- is why the ORDER of the array is semantically meaningful and must be preserved
-- by any writer.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.value_chain_profiles (
    id                  uuid primary key default gen_random_uuid(),
    commodity_id        uuid references public.commodities (id) on delete cascade,
    category            text not null default 'vegetable'
                            check (category in ('vegetable', 'oilseed', 'cereal', 'other')),
    scope_district      text not null default '',
    channel             text not null default 'traditional'
                            check (channel in ('traditional', 'direct')),
    stages              jsonb not null default '[]'::jsonb,
    margin_scale        numeric(8, 5) not null default 1.0
                            check (margin_scale >= 0),
    calibrated_at       timestamptz,
    calibration_status  text check (calibration_status in ('ok', 'glut', 'unreachable', 'given')),
    source_note         text,
    is_active           boolean not null default true,
    created_at          timestamptz not null default now(),

    constraint chk_stages_is_array
        check (jsonb_typeof(stages) = 'array')
);

comment on table public.value_chain_profiles is
  'Ordered stage model of the farm-to-consumer chain. Composed by the engine into '
  'an affine map (retail = A*farm + B) which is then inverted for fair-price discovery. '
  'stages array order is semantically significant.';

create index if not exists idx_vcp_lookup
    on public.value_chain_profiles (commodity_id, channel, is_active);
create index if not exists idx_vcp_category
    on public.value_chain_profiles (category, channel, is_active);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. consumer_nodes — the demand side of a direct trade
--
-- Distinct from `buyers` (008).  A `buyer` is a licensed trade counterparty who
-- already operates in the mandi system.  A `consumer_node` is an END DEMAND
-- point: it does not resell, it consumes.  That distinction is what makes a
-- trade "direct" rather than just one more link.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.consumer_nodes (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid references public.user_profiles (id) on delete set null,
    name                text not null,
    kind                text not null default 'household'
                            check (kind in (
                                'household', 'rwa', 'hostel', 'canteen',
                                'hotel', 'retailer', 'processor', 'institution'
                            )),
    district            text not null default 'Nashik',
    pincode             text,
    lat                 numeric(9, 6),
    lng                 numeric(9, 6),
    commodity_id        uuid references public.commodities (id) on delete set null,
    demand_qtl          numeric(12, 2) not null default 0
                            check (demand_qtl >= 0),
    max_price_per_qtl   numeric(10, 2) check (max_price_per_qtl is null or max_price_per_qtl > 0),
    household_size      integer check (household_size is null or household_size > 0),
    verified            boolean not null default false,
    contact_phone       text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint chk_consumer_lat check (lat is null or (lat between -90 and 90)),
    constraint chk_consumer_lng check (lng is null or (lng between -180 and 180))
);

comment on table public.consumer_nodes is
  'End-demand points for direct farm-to-consumer trade (households, RWAs, hostels, '
  'canteens, hotels, institutions). Distinct from public.buyers, which are licensed '
  'trade counterparties operating inside the mandi system.';

create index if not exists idx_consumer_nodes_commodity
    on public.consumer_nodes (commodity_id, verified);
create index if not exists idx_consumer_nodes_district
    on public.consumer_nodes (district);
create index if not exists idx_consumer_nodes_user
    on public.consumer_nodes (user_id);

drop trigger if exists trg_consumer_nodes_updated_at on public.consumer_nodes;
create trigger trg_consumer_nodes_updated_at
    before update on public.consumer_nodes
    for each row execute function public.set_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. group_buys — pooling consumer orders up to a viable truckload
--
-- A group buy is a *window*: members commit quantity until `deadline`, at which
-- point the pool either clears `min_load_qtl` and is released to the planner, or
-- rolls into the next window.  `released_plan_id` links it to the plan that
-- eventually served it.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.group_buys (
    id                  uuid primary key default gen_random_uuid(),
    organiser_id        uuid references public.user_profiles (id) on delete set null,
    commodity_id        uuid not null references public.commodities (id) on delete restrict,
    district            text not null default 'Nashik',
    lat                 numeric(9, 6),
    lng                 numeric(9, 6),
    target_qtl          numeric(12, 2) not null default 0 check (target_qtl >= 0),
    min_load_qtl        numeric(12, 2) not null default 50 check (min_load_qtl >= 0),
    committed_qtl       numeric(12, 2) not null default 0 check (committed_qtl >= 0),
    deadline            timestamptz not null,
    status              text not null default 'open'
                            check (status in (
                                'open', 'released', 'fulfilled', 'expired', 'cancelled'
                            )),
    released_plan_id    text,   -- DirectPlan.plan_id from the engine
    released_at         timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint chk_group_buy_deadline_future check (deadline > created_at)
);

comment on table public.group_buys is
  'A pooling window: consumer orders accumulate until `deadline`, then release to the '
  'planner if `committed_qtl` clears `min_load_qtl`. Consolidation is what makes small '
  'direct orders economically viable.';

create index if not exists idx_group_buys_commodity_status
    on public.group_buys (commodity_id, status, deadline);

drop trigger if exists trg_group_buys_updated_at on public.group_buys;
create trigger trg_group_buys_updated_at
    before update on public.group_buys
    for each row execute function public.set_updated_at();


create table if not exists public.group_buy_members (
    id              uuid primary key default gen_random_uuid(),
    group_buy_id    uuid not null references public.group_buys (id) on delete cascade,
    consumer_node_id uuid references public.consumer_nodes (id) on delete set null,
    user_id         uuid references public.user_profiles (id) on delete set null,
    qtl             numeric(12, 2) not null check (qtl > 0),
    lat             numeric(9, 6),
    lng             numeric(9, 6),
    label           text,
    created_at      timestamptz not null default now(),

    constraint uq_group_buy_member unique (group_buy_id, consumer_node_id)
);

comment on table public.group_buy_members is
  'One member order inside a group buy. uq_group_buy_member prevents a member '
  'double-committing to the same window (which would inflate committed_qtl).';

create index if not exists idx_group_buy_members_group
    on public.group_buy_members (group_buy_id);


-- =============================================================================
-- ROW LEVEL SECURITY
--
-- Follows the same reasoning as 001: reference data is public good, personal
-- data is owner-only, and operational writes go through SECURITY DEFINER RPCs.
-- =============================================================================

alter table public.retail_prices       enable row level security;
alter table public.value_chain_profiles enable row level security;
alter table public.consumer_nodes      enable row level security;
alter table public.group_buys          enable row level security;
alter table public.group_buy_members   enable row level security;

-- ── retail_prices: public read (a consumer-facing price is public information) ──
drop policy if exists "Public can read retail prices" on public.retail_prices;
create policy "Public can read retail prices"
    on public.retail_prices for select
    using (true);

drop policy if exists "Admins write retail prices" on public.retail_prices;
create policy "Admins write retail prices"
    on public.retail_prices for all
    using (public.has_role('admin'))
    with check (public.has_role('admin'));

-- ── value_chain_profiles: public read (the model must be auditable) ──────────
drop policy if exists "Public can read chain profiles" on public.value_chain_profiles;
create policy "Public can read chain profiles"
    on public.value_chain_profiles for select
    using (true);

drop policy if exists "Admins write chain profiles" on public.value_chain_profiles;
create policy "Admins write chain profiles"
    on public.value_chain_profiles for all
    using (public.has_role('admin'))
    with check (public.has_role('admin'));

-- ── consumer_nodes: a consumer sees and edits their own node only ────────────
-- Aggregate demand is not sensitive individually, but phone and precise
-- coordinates are, so the default is owner-only rather than public read.
drop policy if exists "Consumers read own nodes" on public.consumer_nodes;
create policy "Consumers read own nodes"
    on public.consumer_nodes for select
    using (auth.uid() = user_id or public.has_role('admin'));

drop policy if exists "Consumers create own nodes" on public.consumer_nodes;
create policy "Consumers create own nodes"
    on public.consumer_nodes for insert
    with check (auth.uid() = user_id);

drop policy if exists "Consumers update own nodes" on public.consumer_nodes;
create policy "Consumers update own nodes"
    on public.consumer_nodes for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- ── group_buys: open windows are public (a consumer must be able to join);
--    member rows are visible to the organiser, members and admins only ────────
drop policy if exists "Public can read open group buys" on public.group_buys;
create policy "Public can read open group buys"
    on public.group_buys for select
    using (status = 'open' or auth.uid() = organiser_id or public.has_role('admin'));

drop policy if exists "Users create group buys" on public.group_buys;
create policy "Users create group buys"
    on public.group_buys for insert
    with check (auth.uid() = organiser_id or public.has_role('admin'));

drop policy if exists "Organisers update own group buys" on public.group_buys;
create policy "Organisers update own group buys"
    on public.group_buys for update
    using (auth.uid() = organiser_id or public.has_role('admin'))
    with check (auth.uid() = organiser_id or public.has_role('admin'));

drop policy if exists "Members read own group buy membership" on public.group_buy_members;
create policy "Members read own group buy membership"
    on public.group_buy_members for select
    using (
        auth.uid() = user_id
        or public.has_role('admin')
        or exists (
            select 1 from public.group_buys g
             where g.id = group_buy_id and g.organiser_id = auth.uid()
        )
    );

drop policy if exists "Users join group buys" on public.group_buy_members;
create policy "Users join group buys"
    on public.group_buy_members for insert
    with check (auth.uid() = user_id);
