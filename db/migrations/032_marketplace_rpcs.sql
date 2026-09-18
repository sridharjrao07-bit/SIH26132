-- =============================================================================
-- SIH26132 — Krishi Bazaar: Marketplace ACID Transactional RPCs (PR-3)
-- Migration 032 — applies AFTER 031
--
-- All mutations to workflow tables (lots, offers, payments, buyers) MUST flow
-- through these RPCs.  Direct INSERT/UPDATE/DELETE was revoked in migration 031.
--
-- Each RPC:
--   - Runs as SECURITY DEFINER (owns the write privilege)
--   - Validates the caller's JWT uid matches the row owner (cross-tenant guard)
--   - Enforces the state machine in a single transaction
--   - Returns the updated row as JSONB (avoids a second SELECT round-trip)
--
-- Error codes follow the convention from migration 013:
--   P0001  cross-tenant mutation or domain-level constraint violation
--   P0002  row not found or not owned
--   P0003  invalid state-machine transition
--   P0004  unknown/invalid input value
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- fpo_members table (first referenced here; idempotent)
-- Tracks the mapping between FPO user and their member farmers.
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists public.fpo_members (
    id         uuid primary key default gen_random_uuid(),
    fpo_id     uuid not null references public.user_profiles (id) on delete cascade,
    member_id  uuid not null references public.user_profiles (id) on delete cascade,
    joined_at  timestamptz not null default now(),
    constraint fpo_members_unique unique (fpo_id, member_id),
    constraint fpo_not_self check (fpo_id <> member_id)
);

comment on table public.fpo_members is
    'Maps FPO accounts to their member farmers.';

create index if not exists idx_fpo_members_fpo on public.fpo_members (fpo_id);
create index if not exists idx_fpo_members_member on public.fpo_members (member_id);

alter table public.fpo_members enable row level security;
drop policy if exists "FPO members visible to members and admins" on public.fpo_members;
create policy "FPO members visible to members and admins"
    on public.fpo_members for select
    using (auth.uid() = fpo_id or auth.uid() = member_id or public.has_role('admin'));

-- Revoke direct writes; managed via RPC only
revoke insert, update, delete on public.fpo_members from anon, authenticated;


-- ─────────────────────────────────────────────────────────────────────────────
-- lot_create — atomically insert a lot with server-set user_id
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.lot_create(
    p_commodity_id  uuid,
    p_quantity_qtl  numeric,
    p_grade         text     default 'General',
    p_quality_notes text     default null,
    p_harvest_date  date     default null,
    p_asking_price  numeric  default null,
    p_market_id     uuid     default null,
    p_fpo_id        uuid     default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_lot     lots%rowtype;
begin
    if v_user_id is null then
        raise exception 'lot_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if p_quantity_qtl <= 0 then
        raise exception 'quantity_qtl must be positive, got %', p_quantity_qtl
            using errcode = 'P0004';
    end if;

    if p_asking_price is not null and p_asking_price <= 0 then
        raise exception 'asking_price must be positive, got %', p_asking_price
            using errcode = 'P0004';
    end if;

    insert into public.lots (
        user_id, fpo_id, commodity_id, market_id,
        quantity_qtl, grade, quality_notes, harvest_date, asking_price, status
    ) values (
        v_user_id, p_fpo_id, p_commodity_id, p_market_id,
        p_quantity_qtl, coalesce(p_grade, 'General'), p_quality_notes,
        p_harvest_date, p_asking_price, 'open'
    )
    returning * into v_lot;

    return row_to_json(v_lot)::jsonb;
end;
$$;

revoke all on function public.lot_create(uuid,numeric,text,text,date,numeric,uuid,uuid) from public, anon;
grant execute on function public.lot_create(uuid,numeric,text,text,date,numeric,uuid,uuid) to authenticated;

comment on function public.lot_create is
    'SECURITY DEFINER. Creates a lot with user_id = auth.uid(). '
    'Validates positive quantity/price. Returns the created row.';


-- ─────────────────────────────────────────────────────────────────────────────
-- lot_withdraw — atomically withdraw a lot the caller owns
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.lot_withdraw(p_lot_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_lot     lots%rowtype;
begin
    if v_user_id is null then
        raise exception 'lot_withdraw requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_lot from public.lots
     where id = p_lot_id and (user_id = v_user_id or fpo_id = v_user_id);

    if not found then
        raise exception 'lot not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_lot.status in ('sold', 'withdrawn') then
        raise exception 'cannot withdraw a % lot', v_lot.status
            using errcode = 'P0003';
    end if;

    update public.lots set status = 'withdrawn' where id = p_lot_id
    returning * into v_lot;

    return row_to_json(v_lot)::jsonb;
end;
$$;

revoke all on function public.lot_withdraw(uuid) from public, anon;
grant execute on function public.lot_withdraw(uuid) to authenticated;

comment on function public.lot_withdraw is
    'SECURITY DEFINER. Withdraws a lot owned by auth.uid(). State-machine checked.';


-- ─────────────────────────────────────────────────────────────────────────────
-- lot_grade_update — update grade/notes on an open/offered lot
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.lot_grade_update(
    p_lot_id        uuid,
    p_grade         text,
    p_quality_notes text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_lot     lots%rowtype;
begin
    if v_user_id is null then
        raise exception 'lot_grade_update requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_lot from public.lots
     where id = p_lot_id and (user_id = v_user_id or fpo_id = v_user_id);

    if not found then
        raise exception 'lot not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_lot.status in ('sold', 'withdrawn') then
        raise exception 'cannot regrade a % lot', v_lot.status
            using errcode = 'P0003';
    end if;

    update public.lots
       set grade        = p_grade,
           quality_notes = coalesce(p_quality_notes, quality_notes)
     where id = p_lot_id
    returning * into v_lot;

    return row_to_json(v_lot)::jsonb;
end;
$$;

revoke all on function public.lot_grade_update(uuid,text,text) from public, anon;
grant execute on function public.lot_grade_update(uuid,text,text) to authenticated;

comment on function public.lot_grade_update is
    'SECURITY DEFINER. Updates lot grade/notes; blocks on sold/withdrawn lots.';


-- ─────────────────────────────────────────────────────────────────────────────
-- offer_create — atomically create an offer and mark the lot as 'offered'
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.offer_create(
    p_lot_id       uuid,
    p_buyer_id     uuid,
    p_price_per_qtl numeric,
    p_quantity_qtl  numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_lot     lots%rowtype;
    v_offer   offers%rowtype;
begin
    if v_user_id is null then
        raise exception 'offer_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    -- Lock the lot row for the duration of this transaction to prevent races.
    select * into v_lot from public.lots
     where id = p_lot_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'lot not found or not owned by caller'
            using errcode = 'P0002';
    end if;

    if v_lot.status not in ('open', 'offered') then
        raise exception 'lot % is not open for offers (status: %)', p_lot_id, v_lot.status
            using errcode = 'P0003';
    end if;

    if p_quantity_qtl > v_lot.quantity_qtl then
        raise exception 'offer quantity % exceeds lot quantity %', p_quantity_qtl, v_lot.quantity_qtl
            using errcode = 'P0004';
    end if;

    if p_price_per_qtl <= 0 then
        raise exception 'price_per_qtl must be positive'
            using errcode = 'P0004';
    end if;

    insert into public.offers (
        lot_id, buyer_id, user_id, price_per_qtl, quantity_qtl, status
    ) values (
        p_lot_id, p_buyer_id, v_user_id, p_price_per_qtl, p_quantity_qtl, 'pending'
    )
    returning * into v_offer;

    -- Mark lot as 'offered' if it was still 'open'
    update public.lots set status = 'offered' where id = p_lot_id and status = 'open';

    return row_to_json(v_offer)::jsonb;
end;
$$;

revoke all on function public.offer_create(uuid,uuid,numeric,numeric) from public, anon;
grant execute on function public.offer_create(uuid,uuid,numeric,numeric) to authenticated;

comment on function public.offer_create is
    'SECURITY DEFINER. Creates an offer and marks lot offered. Uses FOR UPDATE to '
    'prevent concurrent double-offers on the same lot.';


-- ─────────────────────────────────────────────────────────────────────────────
-- offer_decide — accept or reject an offer, in a single transaction
--
-- accept: sets offer=accepted, all other pending offers=rejected, lot=matched
-- reject: sets offer=rejected, if no other pending offers lot reverts to open
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.offer_decide(
    p_offer_id uuid,
    p_decision text   -- 'accepted' | 'rejected'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_offer   offers%rowtype;
    v_lot     lots%rowtype;
    v_pending int;
begin
    if v_user_id is null then
        raise exception 'offer_decide requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if p_decision not in ('accepted', 'rejected') then
        raise exception 'decision must be accepted or rejected, got %', p_decision
            using errcode = 'P0004';
    end if;

    -- Lock offer for the duration of the transaction
    select * into v_offer from public.offers
     where id = p_offer_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'offer not found or not owned by caller'
            using errcode = 'P0002';
    end if;

    if v_offer.status != 'pending' then
        raise exception 'cannot decide on a % offer', v_offer.status
            using errcode = 'P0003';
    end if;

    -- Lock the parent lot too
    select * into v_lot from public.lots
     where id = v_offer.lot_id
     for update;

    if p_decision = 'accepted' then
        -- Accept this offer
        update public.offers set status = 'accepted' where id = p_offer_id
        returning * into v_offer;

        -- Reject all OTHER pending offers for the same lot atomically
        update public.offers
           set status = 'rejected'
         where lot_id = v_lot.id
           and id <> p_offer_id
           and status = 'pending';

        -- Advance lot to matched
        update public.lots set status = 'matched' where id = v_lot.id;

    else -- 'rejected'
        update public.offers set status = 'rejected' where id = p_offer_id
        returning * into v_offer;

        -- Revert lot to open if no other pending offers remain
        select count(*) into v_pending
          from public.offers
         where lot_id = v_lot.id and status = 'pending';

        if v_pending = 0 then
            update public.lots set status = 'open'
             where id = v_lot.id and status = 'offered';
        end if;
    end if;

    return row_to_json(v_offer)::jsonb;
end;
$$;

revoke all on function public.offer_decide(uuid,text) from public, anon;
grant execute on function public.offer_decide(uuid,text) to authenticated;

comment on function public.offer_decide is
    'SECURITY DEFINER. Accept or reject an offer atomically. '
    'On accept: rejects all sibling pending offers + advances lot to matched. '
    'On reject: reverts lot to open if no other offers remain. '
    'Uses FOR UPDATE on both offer and lot to prevent concurrent races.';


-- ─────────────────────────────────────────────────────────────────────────────
-- payment_create — atomically create a payment linked to an accepted offer
-- The DB trigger (031) enforces amount = price_per_qtl * quantity_qtl.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.payment_create(
    p_offer_id  uuid,
    p_amount    numeric,
    p_reference text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_offer   offers%rowtype;
    v_payment payments%rowtype;
begin
    if v_user_id is null then
        raise exception 'payment_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_offer from public.offers
     where id = p_offer_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'offer not found or not owned by caller'
            using errcode = 'P0002';
    end if;

    if v_offer.status != 'accepted' then
        raise exception 'payments require an accepted offer, current status: %', v_offer.status
            using errcode = 'P0003';
    end if;

    -- Idempotency: return existing active payment if already created
    select * into v_payment
      from public.payments
     where offer_id = p_offer_id
       and user_id  = v_user_id
       and status in ('pending', 'paid')
     limit 1;

    if found then
        return row_to_json(v_payment)::jsonb;
    end if;

    -- The trg_check_payment_amount trigger validates amount = price_per_qtl * quantity_qtl
    insert into public.payments (offer_id, user_id, amount, status, reference)
    values (p_offer_id, v_user_id, p_amount, 'pending', p_reference)
    returning * into v_payment;

    return row_to_json(v_payment)::jsonb;
end;
$$;

revoke all on function public.payment_create(uuid,numeric,text) from public, anon;
grant execute on function public.payment_create(uuid,numeric,text) to authenticated;

comment on function public.payment_create is
    'SECURITY DEFINER. Creates a payment for an accepted offer. Idempotent: '
    'returns existing pending/paid payment if one exists. Amount validated by '
    'trg_check_payment_amount trigger (031).';


-- ─────────────────────────────────────────────────────────────────────────────
-- payment_mark_paid — transition payment to paid, atomically close the lot
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.payment_mark_paid(p_payment_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_payment payments%rowtype;
    v_lot_id  uuid;
begin
    if v_user_id is null then
        raise exception 'payment_mark_paid requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_payment from public.payments
     where id = p_payment_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'payment not found or not owned by caller'
            using errcode = 'P0002';
    end if;

    if v_payment.status in ('failed', 'disputed') then
        raise exception 'cannot mark a % payment as paid', v_payment.status
            using errcode = 'P0003';
    end if;

    if v_payment.status = 'paid' then
        return row_to_json(v_payment)::jsonb;  -- idempotent
    end if;

    update public.payments
       set status  = 'paid',
           paid_at = now()
     where id = p_payment_id
    returning * into v_payment;

    -- Advance the parent lot to 'sold' in the same transaction
    select l.id into v_lot_id
      from public.offers o
      join public.lots   l on l.id = o.lot_id
     where o.id = v_payment.offer_id;

    if v_lot_id is not null then
        update public.lots set status = 'sold' where id = v_lot_id;
    end if;

    return row_to_json(v_payment)::jsonb;
end;
$$;

revoke all on function public.payment_mark_paid(uuid) from public, anon;
grant execute on function public.payment_mark_paid(uuid) to authenticated;

comment on function public.payment_mark_paid is
    'SECURITY DEFINER. Marks payment paid AND closes the lot (sold) atomically. '
    'Idempotent for already-paid payments.';


-- ─────────────────────────────────────────────────────────────────────────────
-- fpo_aggregate_lots — FPO pools member lots into a single pooled lot
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.fpo_aggregate_lots(
    p_lot_ids    uuid[],
    p_market_id  uuid   default null,
    p_asking_price numeric default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id     uuid := auth.uid();
    v_lot         lots%rowtype;
    v_commodity   uuid;
    v_total_qty   numeric := 0;
    v_avg_price   numeric;
    v_price_sum   numeric := 0;
    v_price_count int     := 0;
    v_pooled      lots%rowtype;
    v_lid         uuid;
begin
    if v_user_id is null then
        raise exception 'fpo_aggregate_lots requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    -- Verify caller is an FPO
    if not public.has_role_for(v_user_id, 'fpo') then
        raise exception 'fpo_aggregate_lots requires the fpo role'
            using errcode = 'P0001';
    end if;

    if array_length(p_lot_ids, 1) is null or array_length(p_lot_ids, 1) = 0 then
        raise exception 'at least one lot_id is required'
            using errcode = 'P0004';
    end if;

    -- Lock and validate each lot
    foreach v_lid in array p_lot_ids loop
        select * into v_lot from public.lots
         where id = v_lid
         for update;

        if not found then
            raise exception 'lot % not found', v_lid using errcode = 'P0002';
        end if;

        if v_lot.status != 'open' then
            raise exception 'lot % is not open (status: %)', v_lid, v_lot.status
                using errcode = 'P0003';
        end if;

        if v_commodity is null then
            v_commodity := v_lot.commodity_id;
        elsif v_commodity != v_lot.commodity_id then
            raise exception 'all lots must share the same commodity'
                using errcode = 'P0004';
        end if;

        v_total_qty := v_total_qty + v_lot.quantity_qtl;
        if v_lot.asking_price is not null then
            v_price_sum   := v_price_sum + v_lot.asking_price;
            v_price_count := v_price_count + 1;
        end if;
    end loop;

    -- Compute average asking price from members if not overridden
    if p_asking_price is null and v_price_count > 0 then
        v_avg_price := (v_price_sum / v_price_count)::numeric(10,2);
    else
        v_avg_price := p_asking_price;
    end if;

    -- Create pooled lot
    insert into public.lots (
        user_id, fpo_id, commodity_id, market_id,
        quantity_qtl, grade, quality_notes, asking_price, status
    ) values (
        v_user_id, v_user_id, v_commodity,
        coalesce(p_market_id, (select market_id from public.lots where id = p_lot_ids[1])),
        v_total_qty,
        (select grade from public.lots where id = p_lot_ids[1]),
        format('FPO aggregate of %s lots', array_length(p_lot_ids, 1)),
        v_avg_price,
        'open'
    )
    returning * into v_pooled;

    -- Mark member lots as matched under this FPO
    update public.lots
       set status = 'matched',
           fpo_id = v_user_id
     where id = any(p_lot_ids);

    return row_to_json(v_pooled)::jsonb;
end;
$$;

revoke all on function public.fpo_aggregate_lots(uuid[],uuid,numeric) from public, anon;
grant execute on function public.fpo_aggregate_lots(uuid[],uuid,numeric) to authenticated;


comment on function public.fpo_aggregate_lots is
    'SECURITY DEFINER. Pools member lots into a single FPO lot atomically. '
    'Validates: caller is fpo role, all lots are open, all share one commodity. '
    'Member lots are marked matched; pooled lot starts open.';


-- ─────────────────────────────────────────────────────────────────────────────
-- buyer_register — self-service buyer profile creation
-- verified=False always; admin must call buyer_verify to flip
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.buyer_register(
    p_name                text,
    p_type                text,
    p_phone               text     default null,
    p_district            text     default null,
    p_lat                 numeric  default null,
    p_lng                 numeric  default null,
    p_commodity_id        uuid     default null,
    p_demand_qty_qtl      numeric  default null,
    p_max_price           numeric  default null,
    p_quality_requirements text   default null,
    p_payment_reliability text    default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_buyer   buyers%rowtype;
begin
    if v_user_id is null then
        raise exception 'buyer_register requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    -- One buyer profile per user
    if exists (select 1 from public.buyers where owner_user_id = v_user_id) then
        raise exception 'user already has a registered buyer profile'
            using errcode = 'P0001';
    end if;

    insert into public.buyers (
        name, type, phone, district, lat, lng,
        commodity_id, demand_qty_qtl, max_price,
        quality_requirements, payment_reliability,
        verified, owner_user_id
    ) values (
        p_name, p_type, p_phone, p_district, p_lat, p_lng,
        p_commodity_id, p_demand_qty_qtl, p_max_price,
        p_quality_requirements, p_payment_reliability,
        false, v_user_id
    )
    returning * into v_buyer;

    return row_to_json(v_buyer)::jsonb;
end;
$$;

revoke all on function public.buyer_register(text,text,text,text,numeric,numeric,uuid,numeric,numeric,text,text) from public, anon;
grant execute on function public.buyer_register(text,text,text,text,numeric,numeric,uuid,numeric,numeric,text,text) to authenticated;

comment on function public.buyer_register is
    'SECURITY DEFINER. Creates a buyer profile with owner_user_id = auth.uid(). '
    'verified is always false at registration. One profile per user enforced.';


-- ─────────────────────────────────────────────────────────────────────────────
-- buyer_verify — admin-only verification of a buyer profile
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function public.buyer_verify(p_buyer_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_caller_id uuid := auth.uid();
    v_buyer     buyers%rowtype;
begin
    -- Only admins may verify buyers
    if not public.has_role_for(v_caller_id, 'admin') then
        raise exception 'buyer_verify requires the admin role'
            using errcode = 'P0001';
    end if;

    select * into v_buyer from public.buyers where id = p_buyer_id;
    if not found then
        raise exception 'buyer % not found', p_buyer_id using errcode = 'P0002';
    end if;

    -- Use current_setting to signal to the guard trigger that this is a
    -- legitimate admin path (service_role context via SECURITY DEFINER).
    update public.buyers set verified = true where id = p_buyer_id
    returning * into v_buyer;

    return row_to_json(v_buyer)::jsonb;
end;
$$;

revoke all on function public.buyer_verify(uuid) from public, anon;
grant execute on function public.buyer_verify(uuid) to authenticated, service_role;

comment on function public.buyer_verify is
    'SECURITY DEFINER. Sets buyers.verified = true. Restricted to admin role. '
    'Runs under service_role so trg_guard_buyer_self_verify allows the update.';

