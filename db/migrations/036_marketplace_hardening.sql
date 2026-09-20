-- =============================================================================
-- SIH26132 — Krishi Bazaar: Audit remediation — marketplace hardening
-- Migration 036 — applies AFTER 035
--
-- Fixes from the 2026-09-20 backend security audit.  Each fix is a
-- CREATE OR REPLACE of a function introduced in 008/013/032/035 (or a brand
-- new function), because 032/035 are already recorded in schema_migrations on
-- existing databases and would be skipped — a new migration is the only way
-- live databases receive the corrected bodies.
--
--  C3   booking writes: 031 revoked direct INSERT/UPDATE on storage_bookings
--       and logistics_bookings, but no RPC was ever written — every booking
--       POST/PATCH returned 42501, and the Python-side capacity check was a
--       TOCTOU race.  → four new SECURITY DEFINER booking RPCs with row locks.
--  C4   offer_create never checked buyers.verified — an unverified buyer
--       could receive and win offers.  → verified-buyer gate.
--  C5   offer TTL: LOT_STATUS_REGRESSION blocked the offered→open reopen after
--       expiry, and 72h-old pending offers were still decidable.  → the
--       regression trigger now allows the reopen; offer_decide enforces the
--       48h TTL server-side.
--  C6   transition_payment_status read the payment without FOR UPDATE — a
--       concurrent paid+failed pair left the lot 'sold' with a 'failed'
--       payment.  → row lock; the state machine then rejects the loser.
--  C7   lot_withdraw allowed withdrawing a lot after an offer was accepted,
--       and payment_mark_paid happily sold a withdrawn lot.  → matched lots
--       cannot be withdrawn; payment_mark_paid locks and checks the lot.
--  C8   payment_create idempotency only covered pending/paid — a disputed or
--       failed payment let a second payment be created for the same offer.
--       → idempotent across ALL statuses + unique index on payments(offer_id).
--  C9   offer_decide locked (offer, lot, siblings) in inconsistent order —
--       two concurrent accepts on sibling offers deadlocked (40P01).
--       → lock the parent lot first, then the offer.
--  C10  fpo_aggregate_lots counted a repeated lot id twice (10 qtl → 20 qtl).
--       → de-duplicated, deterministically ordered locking.
--  C11  buyer_verify was dead: it runs SECURITY DEFINER as its owner, so the
--       guard trigger's current_setting('role') check could never see
--       'service_role' and blocked even the legitimate admin path.
--       → explicit transaction-scoped authorization flag.
--  +    payments.user_id ON DELETE CASCADE erased paid-payment history when a
--       user was deleted.  → ON DELETE RESTRICT.
--
-- Concurrency contract (deadlock-freedom): every RPC that touches both a lot
-- and its offers/payments locks the LOT row first.  offer_create (lot → offer
-- insert), offer_decide (lot → offer), payment_mark_paid (payment → lot —
-- never touches offers, so no cycle with offer_decide), lot_withdraw (lot
-- only), fpo_aggregate_lots (lots in ascending id order).
--
-- All changes are idempotent (CREATE OR REPLACE / IF NOT EXISTS).
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Lot lifecycle
-- ─────────────────────────────────────────────────────────────────────────────

-- A1 (C5). guard_lot_status_regression: 'offered' → 'open' is a legitimate
-- lifecycle event (all offers rejected/expired and the lot re-enters the
-- market), not a regression.  Without this exception the expiry sweeper and
-- offer_decide's reject path both fail with LOT_STATUS_REGRESSION and the lot
-- is stuck in 'offered' forever.  Everything else stays monotonic.
create or replace function public.guard_lot_status_regression()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    v_weights  json := '{"open":0,"offered":1,"matched":2,"sold":3,"withdrawn":3}';
    v_old_w    int;
    v_new_w    int;
begin
    -- Reopen: every offer on the lot was rejected or expired.
    if old.status = 'offered' and new.status = 'open' then
        return new;
    end if;

    v_old_w := (v_weights ->> old.status)::int;
    v_new_w := (v_weights ->> new.status)::int;

    if v_old_w is null or v_new_w is null then
        -- Unknown status value — already caught by the CHECK constraint.
        return new;
    end if;

    if v_new_w < v_old_w then
        raise exception 'LOT_STATUS_REGRESSION'
            using detail = format(
                'lot %s: cannot move status from %s to %s',
                old.id, old.status, new.status
            );
    end if;

    return new;
end;
$$;

comment on function public.guard_lot_status_regression() is
    'Prevents lot.status from regressing to an earlier lifecycle state, '
    'except the legitimate offered→open reopen when all offers are gone.';

-- A2 (C7). lot_withdraw: lock the row, and refuse to withdraw a lot whose
-- offer has been accepted ('matched') — the buyer is already committed.
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
     where id = p_lot_id and (user_id = v_user_id or fpo_id = v_user_id)
     for update;

    if not found then
        raise exception 'lot not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_lot.status in ('sold', 'withdrawn', 'matched') then
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
    'SECURITY DEFINER. Withdraws a lot owned by auth.uid(). State-machine '
    'checked; matched/sold/withdrawn lots cannot be withdrawn.';

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Offers
-- ─────────────────────────────────────────────────────────────────────────────

-- B1 (C4). offer_create: the buyer must exist and be verified.
create or replace function public.offer_create(
    p_lot_id        uuid,
    p_buyer_id      uuid,
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
    v_verified boolean;
begin
    if v_user_id is null then
        raise exception 'offer_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    -- C4: only verified buyers can receive offers.  The buyers table is
    -- public-read only for verified rows; this definer check closes the
    -- unverified-buyer hole regardless of what the caller can see.
    select b.verified into v_verified
      from public.buyers b
     where b.id = p_buyer_id;

    if not found then
        raise exception 'buyer % not found', p_buyer_id
            using errcode = 'P0002';
    end if;

    if v_verified is not true then
        raise exception 'offers can only be created for verified buyers'
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
    'SECURITY DEFINER. Creates an offer for a VERIFIED buyer and marks lot '
    'offered. Uses FOR UPDATE to prevent concurrent double-offers.';

-- B2 (C9 + C5). offer_decide: lock the parent lot BEFORE the offer so two
-- concurrent decisions on sibling offers serialize instead of deadlocking,
-- and enforce the 48-hour pending-offer TTL server-side.
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
    v_lot_id  uuid;
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

    -- Locate the offer (ownership check) without locking, only to learn
    -- which lot must be locked first.  offers.lot_id / user_id are immutable.
    select lot_id into v_lot_id from public.offers
     where id = p_offer_id and user_id = v_user_id;

    if not found then
        raise exception 'offer not found or not owned by caller'
            using errcode = 'P0002';
    end if;

    -- C9: LOT FIRST, then offer.  The previous order (offer, lot, siblings)
    -- let two transactions each hold one sibling offer and wait on the other's
    -- sibling sweep — a guaranteed 40P01 under concurrent accepts.  Locking
    -- the shared parent first serializes all decisions for a lot.
    select * into v_lot from public.lots
     where id = v_lot_id
     for update;

    if not found then
        raise exception 'parent lot not found'
            using errcode = 'P0002';
    end if;

    select * into v_offer from public.offers
     where id = p_offer_id
     for update;

    if v_offer.status != 'pending' then
        raise exception 'cannot decide on a % offer', v_offer.status
            using errcode = 'P0003';
    end if;

    -- C5: the 48-hour TTL is enforced here, not only by the hourly sweeper.
    -- (Keep in sync with OFFER_TTL_HOURS in app/services/marketplace.py.)
    if v_offer.created_at < now() - interval '48 hours' then
        raise exception 'offer % expired: pending offers are decidable for 48 hours only',
                p_offer_id
            using errcode = 'P0003';
    end if;

    if p_decision = 'accepted' then
        update public.offers set status = 'accepted' where id = p_offer_id
        returning * into v_offer;

        -- Reject all OTHER pending offers for the same lot atomically.
        update public.offers
           set status = 'rejected'
         where lot_id = v_lot.id
           and id <> p_offer_id
           and status = 'pending';

        update public.lots set status = 'matched' where id = v_lot.id;

    else -- 'rejected'
        update public.offers set status = 'rejected' where id = p_offer_id
        returning * into v_offer;

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
    'SECURITY DEFINER. Accept or reject an offer atomically. Locks the parent '
    'lot before the offer (deadlock-free under sibling contention) and rejects '
    'pending offers older than 48 hours.';

-- ─────────────────────────────────────────────────────────────────────────────
-- C. Payments
-- ─────────────────────────────────────────────────────────────────────────────

-- C1 (C6). transition_payment_status: read the row FOR UPDATE so the state
-- machine sees the committed status, not a stale snapshot.  Two concurrent
-- transitions now serialize; the loser re-reads under lock and is rejected
-- ('cannot fail a paid payment') instead of leaving lot=sold + payment=failed.
create or replace function public.transition_payment_status(
    p_user_id   uuid,
    p_payment_id uuid,
    p_new_status text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_payment payments%rowtype;
    v_paid_at timestamptz;
begin
    if auth.uid() is not null and auth.uid() <> p_user_id then
        raise exception 'cross-tenant mutation rejected: caller % != owner %', auth.uid(), p_user_id
            using errcode = 'P0001';
    end if;

    select * into v_payment
    from public.payments
    where id = p_payment_id and user_id = p_user_id
    for update;

    if not found then
        raise exception 'payment not found or not owned by user' using errcode = 'P0002';
    end if;

    if p_new_status = 'paid' then
        if v_payment.status in ('failed', 'disputed') then
            raise exception 'cannot mark a % payment as paid', v_payment.status
                using errcode = 'P0003';
        end if;
        v_paid_at := now();
    elsif p_new_status = 'failed' then
        if v_payment.status = 'paid' then
            raise exception 'cannot fail a paid payment' using errcode = 'P0003';
        end if;
    elsif p_new_status = 'disputed' then
        null;
    else
        raise exception 'unknown target status: %', p_new_status using errcode = 'P0004';
    end if;

    update public.payments
    set status  = p_new_status,
        paid_at = coalesce(v_paid_at, paid_at)
    where id = p_payment_id;

    return (select row_to_json(p.*)::jsonb from public.payments p where p.id = p_payment_id);
end;
$$;

revoke all on function public.transition_payment_status(uuid, uuid, text) from public, anon;
grant execute on function public.transition_payment_status(uuid, uuid, text) to authenticated, service_role;

comment on function public.transition_payment_status is
    'SECURITY DEFINER. Asserts ownership and validates the payment state '
    'machine under a row lock (FOR UPDATE) before updating.';

-- C2 (C8). payment_create: idempotent across ALL statuses.
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

    -- C8: idempotency must cover every status.  Returning only on
    -- pending/paid let a disputed/failed payment spawn a SECOND payment for
    -- the same offer (double billing).  One offer, one payment, ever —
    -- backed by uq_payments_one_per_offer below.
    select * into v_payment
      from public.payments
     where offer_id = p_offer_id
       and user_id  = v_user_id
     limit 1;

    if found then
        return row_to_json(v_payment)::jsonb;
    end if;

    insert into public.payments (offer_id, user_id, amount, status, reference)
    values (p_offer_id, v_user_id, p_amount, 'pending', p_reference)
    returning * into v_payment;

    return row_to_json(v_payment)::jsonb;
end;
$$;

revoke all on function public.payment_create(uuid,numeric,text) from public, anon;
grant execute on function public.payment_create(uuid,numeric,text) to authenticated;

comment on function public.payment_create is
    'SECURITY DEFINER. Creates a payment for an accepted offer. Idempotent for '
    'ANY existing payment status (one payment per offer, enforced by '
    'uq_payments_one_per_offer).';

-- C8 (structural): make double-payment impossible even for direct writes.
create unique index if not exists uq_payments_one_per_offer
    on public.payments (offer_id);

comment on index public.uq_payments_one_per_offer is
    'One payment row per offer — closes the dispute/failed re-payment hole.';

-- C3 (C7). payment_mark_paid: resolve and lock the parent lot BEFORE flipping
-- the payment, and never sell a withdrawn lot.
create or replace function public.payment_mark_paid(p_payment_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_payment payments%rowtype;
    v_lot     lots%rowtype;
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

    -- Lock the lot first so a concurrent lot_withdraw on the same lot
    -- serializes against this transaction (C7).
    select l.* into v_lot
      from public.offers o
      join public.lots   l on l.id = o.lot_id
     where o.id = v_payment.offer_id
     for update of l;

    if not found then
        raise exception 'payment % has no resolvable lot', p_payment_id
            using errcode = 'P0003';
    end if;

    if v_lot.status = 'withdrawn' then
        raise exception 'cannot mark paid: lot % was withdrawn', v_lot.id
            using errcode = 'P0003';
    end if;

    update public.payments
       set status  = 'paid',
           paid_at = now()
     where id = p_payment_id
    returning * into v_payment;

    if v_lot.status is distinct from 'sold' then
        update public.lots set status = 'sold' where id = v_lot.id;
    end if;

    return row_to_json(v_payment)::jsonb;
end;
$$;

revoke all on function public.payment_mark_paid(uuid) from public, anon;
grant execute on function public.payment_mark_paid(uuid) to authenticated;

comment on function public.payment_mark_paid is
    'SECURITY DEFINER. Marks payment paid AND closes the lot (sold) atomically. '
    'Locks the lot row and refuses withdrawn lots. Idempotent.';

-- ─────────────────────────────────────────────────────────────────────────────
-- D. FPO aggregation (C10)
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.fpo_aggregate_lots(
    p_lot_ids      uuid[],
    p_market_id    uuid    default null,
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
    v_ids         uuid[];
begin
    if v_user_id is null then
        raise exception 'fpo_aggregate_lots requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if not public.has_role_for(v_user_id, 'fpo') then
        raise exception 'fpo_aggregate_lots requires the fpo role'
            using errcode = 'P0001';
    end if;

    -- C10: de-duplicate the input.  A repeated lot id used to be validated
    -- twice and its quantity counted twice (10 qtl listed twice → a 20 qtl
    -- pooled lot).  Ordering the array also gives every concurrent
    -- aggregation a deterministic lock order.
    select array(select distinct x from unnest(p_lot_ids) as t(x) order by x)
      into v_ids;

    if v_ids is null or array_length(v_ids, 1) = 0 then
        raise exception 'at least one lot_id is required'
            using errcode = 'P0004';
    end if;

    foreach v_lid in array v_ids loop
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

        -- NULL-safe: lots.fpo_id is nullable (008_marketplace.sql, on delete set null).
        -- Plain `!=` evaluates to NULL for farmer lots, silently accepting them.
        if v_lot.fpo_id is distinct from v_user_id then
            raise exception 'lot % does not belong to your FPO', v_lid
                using errcode = 'P0001';
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

    if p_asking_price is null and v_price_count > 0 then
        v_avg_price := (v_price_sum / v_price_count)::numeric(10,2);
    else
        v_avg_price := p_asking_price;
    end if;

    insert into public.lots (
        user_id, fpo_id, commodity_id, market_id,
        quantity_qtl, grade, quality_notes, asking_price, status
    ) values (
        v_user_id, v_user_id, v_commodity,
        coalesce(p_market_id, (select market_id from public.lots where id = v_ids[1])),
        v_total_qty,
        (select grade from public.lots where id = v_ids[1]),
        format('FPO aggregate of %s lots', array_length(v_ids, 1)),
        v_avg_price,
        'open'
    )
    returning * into v_pooled;

    update public.lots
       set status = 'matched',
           fpo_id = v_user_id
     where id = any(v_ids);

    return row_to_json(v_pooled)::jsonb;
end;
$$;

revoke all on function public.fpo_aggregate_lots(uuid[],uuid,numeric) from public, anon;
grant execute on function public.fpo_aggregate_lots(uuid[],uuid,numeric) to authenticated;

comment on function public.fpo_aggregate_lots is
    'SECURITY DEFINER. Pools member lots into a single FPO lot atomically. '
    'De-duplicates input ids, validates: caller is fpo role, all lots are open '
    'and belong to the FPO, all share one commodity.';

-- ─────────────────────────────────────────────────────────────────────────────
-- E. Buyer verification (C11)
-- ─────────────────────────────────────────────────────────────────────────────

-- The guard cannot use role inspection to authorize the admin path: trigger
-- and RPC are SECURITY DEFINER, so both execute as the function owner and
-- current_setting('role') is the owner, not the caller.  buyer_verify
-- therefore sets a transaction-scoped flag the guard honours.  The flag is
-- invisible to other sessions and cannot outlive the transaction.
create or replace function public.guard_buyer_self_verify()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    -- Legitimate admin path: buyer_verify (admin-gated RPC) set the flag.
    if coalesce(current_setting('app.buyer_verify_authorized', true), 'off') = 'on' then
        return new;
    end if;

    -- Direct service_role updates through PostgREST remain allowed.
    if current_setting('role') = 'service_role' then
        return new;
    end if;

    if old.verified is distinct from new.verified then
        raise exception 'BUYER_SELF_VERIFY_FORBIDDEN'
            using detail = 'buyers.verified can only be changed by an admin via buyer_verify';
    end if;

    return new;
end;
$$;

comment on function public.guard_buyer_self_verify() is
    'Prevents direct self-verification of buyers; verified can only be flipped '
    'by the admin-gated buyer_verify RPC (transaction flag) or service_role.';

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
    if not public.has_role_for(v_caller_id, 'admin') then
        raise exception 'buyer_verify requires the admin role'
            using errcode = 'P0001';
    end if;

    select * into v_buyer from public.buyers where id = p_buyer_id;
    if not found then
        raise exception 'buyer % not found', p_buyer_id using errcode = 'P0002';
    end if;

    -- Authorize the guard trigger for this transaction (C11): role
    -- inspection inside SECURITY DEFINER sees the owner, never the caller.
    perform set_config('app.buyer_verify_authorized', 'on', true);

    update public.buyers set verified = true where id = p_buyer_id
    returning * into v_buyer;

    return row_to_json(v_buyer)::jsonb;
end;
$$;

revoke all on function public.buyer_verify(uuid) from public, anon;
grant execute on function public.buyer_verify(uuid) to authenticated, service_role;

comment on function public.buyer_verify is
    'SECURITY DEFINER. Sets buyers.verified = true. Restricted to the admin '
    'role (has_role_for on auth.uid()). Authorizes the guard trigger via a '
    'transaction-scoped flag.';

-- ─────────────────────────────────────────────────────────────────────────────
-- F. Booking RPCs (C3) — 031 revoked direct writes on storage_bookings and
--    logistics_bookings but no RPC ever existed; every booking mutation died
--    with 42501 and capacity was checked in Python (TOCTOU).  These four
--    SECURITY DEFINER functions own the invariants: ownership, lot state,
--    facility existence/active, capacity under a row lock, state machine.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.storage_booking_create(
    p_lot_id             uuid,
    p_facility_id        uuid,
    p_quantity_qtl       numeric default null,
    p_storage_start_date date    default null,
    p_storage_end_date   date    default null,
    p_notes              text    default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id  uuid := auth.uid();
    v_lot      lots%rowtype;
    v_facility storage_facilities%rowtype;
    v_qty      numeric;
    v_used     numeric;
    v_booking  storage_bookings%rowtype;
begin
    if v_user_id is null then
        raise exception 'storage_booking_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_lot from public.lots
     where id = p_lot_id and (user_id = v_user_id or fpo_id = v_user_id)
     for update;

    if not found then
        raise exception 'lot not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_lot.status in ('sold', 'withdrawn') then
        raise exception 'cannot book storage for a % lot', v_lot.status
            using errcode = 'P0003';
    end if;

    v_qty := coalesce(p_quantity_qtl, v_lot.quantity_qtl);
    if v_qty is null or v_qty <= 0 or v_qty > v_lot.quantity_qtl then
        raise exception 'booking quantity must be positive and not exceed the lot quantity (%)',
                v_lot.quantity_qtl
            using errcode = 'P0004';
    end if;

    -- Existence + active check and capacity serialization in one lock.
    select * into v_facility from public.storage_facilities
     where id = p_facility_id and is_active = true
     for update;

    if not found then
        raise exception 'storage facility not found or inactive'
            using errcode = 'P0002';
    end if;

    if v_facility.capacity_qtl is not null then
        select coalesce(sum(quantity_qtl), 0) into v_used
          from public.storage_bookings
         where facility_id = p_facility_id
           and status in ('requested', 'confirmed');

        if v_used + v_qty > v_facility.capacity_qtl then
            raise exception 'facility capacity exceeded: % of % qtl already booked',
                    v_used, v_facility.capacity_qtl
                using errcode = 'P0001';
        end if;
    end if;

    insert into public.storage_bookings (
        user_id, lot_id, facility_id, quantity_qtl, status,
        storage_start_date, storage_end_date, notes
    ) values (
        v_user_id, p_lot_id, p_facility_id, v_qty, 'requested',
        p_storage_start_date, p_storage_end_date, p_notes
    )
    returning * into v_booking;

    return row_to_json(v_booking)::jsonb;
end;
$$;

revoke all on function public.storage_booking_create(uuid,uuid,numeric,date,date,text) from public, anon;
grant execute on function public.storage_booking_create(uuid,uuid,numeric,date,date,text) to authenticated;

comment on function public.storage_booking_create is
    'SECURITY DEFINER. Books storage for a lot the caller owns. Validates lot '
    'state, facility active, and capacity under a facility row lock (no TOCTOU).';

create or replace function public.storage_booking_update(
    p_booking_id uuid,
    p_new_status text,
    p_notes      text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id  uuid := auth.uid();
    v_booking  storage_bookings%rowtype;
    v_facility storage_facilities%rowtype;
    v_used     numeric;
begin
    if v_user_id is null then
        raise exception 'storage_booking_update requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if p_new_status not in ('confirmed', 'cancelled', 'completed') then
        raise exception 'invalid booking status: %', p_new_status
            using errcode = 'P0004';
    end if;

    select * into v_booking from public.storage_bookings
     where id = p_booking_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'booking not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_booking.status in ('cancelled', 'completed') then
        raise exception 'cannot transition from %', v_booking.status
            using errcode = 'P0003';
    end if;

    if not (
        (v_booking.status = 'requested' and p_new_status in ('confirmed', 'cancelled'))
        or (v_booking.status = 'confirmed' and p_new_status in ('completed', 'cancelled'))
    ) then
        raise exception 'cannot move booking from % to %', v_booking.status, p_new_status
            using errcode = 'P0003';
    end if;

    -- Defensive capacity guard when the target state still holds space.
    if p_new_status = 'confirmed' then
        select * into v_facility from public.storage_facilities
         where id = v_booking.facility_id and is_active = true
         for update;

        if not found then
            raise exception 'storage facility not found or inactive'
                using errcode = 'P0002';
        end if;

        if v_facility.capacity_qtl is not null then
            select coalesce(sum(quantity_qtl), 0) into v_used
              from public.storage_bookings
             where facility_id = v_booking.facility_id
               and status in ('requested', 'confirmed')
               and id <> p_booking_id;

            if v_used + v_booking.quantity_qtl > v_facility.capacity_qtl then
                raise exception 'facility capacity exceeded: % of % qtl already booked',
                        v_used, v_facility.capacity_qtl
                    using errcode = 'P0001';
            end if;
        end if;
    end if;

    update public.storage_bookings
       set status = p_new_status,
           notes  = coalesce(p_notes, notes)
     where id = p_booking_id
    returning * into v_booking;

    return row_to_json(v_booking)::jsonb;
end;
$$;

revoke all on function public.storage_booking_update(uuid,text,text) from public, anon;
grant execute on function public.storage_booking_update(uuid,text,text) to authenticated;

comment on function public.storage_booking_update is
    'SECURITY DEFINER. Owner-only booking status transition with a proper '
    'state machine (requested→confirmed→completed, cancel from requested/confirmed).';

create or replace function public.logistics_booking_create(
    p_lot_id         uuid,
    p_logistics_id   uuid,
    p_quantity_qtl   numeric default null,
    p_scheduled_date date    default null,
    p_notes          text    default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_lot     lots%rowtype;
    v_option  logistics_options%rowtype;
    v_qty     numeric;
    v_used    numeric;
    v_booking logistics_bookings%rowtype;
begin
    if v_user_id is null then
        raise exception 'logistics_booking_create requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    select * into v_lot from public.lots
     where id = p_lot_id and (user_id = v_user_id or fpo_id = v_user_id)
     for update;

    if not found then
        raise exception 'lot not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_lot.status in ('sold', 'withdrawn') then
        raise exception 'cannot book logistics for a % lot', v_lot.status
            using errcode = 'P0003';
    end if;

    v_qty := coalesce(p_quantity_qtl, v_lot.quantity_qtl);
    if v_qty is null or v_qty <= 0 or v_qty > v_lot.quantity_qtl then
        raise exception 'booking quantity must be positive and not exceed the lot quantity (%)',
                v_lot.quantity_qtl
            using errcode = 'P0004';
    end if;

    select * into v_option from public.logistics_options
     where id = p_logistics_id and is_active = true
     for update;

    if not found then
        raise exception 'logistics option not found or inactive'
            using errcode = 'P0002';
    end if;

    if v_option.capacity_qtl is not null then
        select coalesce(sum(quantity_qtl), 0) into v_used
          from public.logistics_bookings
         where logistics_id = p_logistics_id
           and status in ('requested', 'confirmed');

        if v_used + v_qty > v_option.capacity_qtl then
            raise exception 'not enough capacity at %: % of % qtl already booked',
                    v_option.name, v_used, v_option.capacity_qtl
                using errcode = 'P0001';
        end if;
    end if;

    insert into public.logistics_bookings (
        user_id, lot_id, logistics_id, kind, quantity_qtl, status,
        scheduled_date, notes
    ) values (
        v_user_id, p_lot_id, p_logistics_id, v_option.kind, v_qty, 'requested',
        p_scheduled_date, p_notes
    )
    returning * into v_booking;

    return row_to_json(v_booking)::jsonb;
end;
$$;

revoke all on function public.logistics_booking_create(uuid,uuid,numeric,date,text) from public, anon;
grant execute on function public.logistics_booking_create(uuid,uuid,numeric,date,text) to authenticated;

comment on function public.logistics_booking_create is
    'SECURITY DEFINER. Books transport/storage logistics for a lot the caller '
    'owns. Capacity enforced under an option row lock (no TOCTOU).';

create or replace function public.logistics_booking_update(
    p_booking_id uuid,
    p_new_status text,
    p_notes      text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid := auth.uid();
    v_booking logistics_bookings%rowtype;
    v_option  logistics_options%rowtype;
    v_used    numeric;
begin
    if v_user_id is null then
        raise exception 'logistics_booking_update requires an authenticated caller'
            using errcode = 'P0001';
    end if;

    if p_new_status not in ('confirmed', 'cancelled', 'completed') then
        raise exception 'invalid booking status: %', p_new_status
            using errcode = 'P0004';
    end if;

    select * into v_booking from public.logistics_bookings
     where id = p_booking_id and user_id = v_user_id
     for update;

    if not found then
        raise exception 'booking not found or access denied'
            using errcode = 'P0002';
    end if;

    if v_booking.status in ('cancelled', 'completed') then
        raise exception 'cannot transition from %', v_booking.status
            using errcode = 'P0003';
    end if;

    if not (
        (v_booking.status = 'requested' and p_new_status in ('confirmed', 'cancelled'))
        or (v_booking.status = 'confirmed' and p_new_status in ('completed', 'cancelled'))
    ) then
        raise exception 'cannot move booking from % to %', v_booking.status, p_new_status
            using errcode = 'P0003';
    end if;

    if p_new_status = 'confirmed' then
        select * into v_option from public.logistics_options
         where id = v_booking.logistics_id and is_active = true
         for update;

        if not found then
            raise exception 'logistics option not found or inactive'
                using errcode = 'P0002';
        end if;

        if v_option.capacity_qtl is not null then
            select coalesce(sum(quantity_qtl), 0) into v_used
              from public.logistics_bookings
             where logistics_id = v_booking.logistics_id
               and status in ('requested', 'confirmed')
               and id <> p_booking_id;

            if v_used + v_booking.quantity_qtl > v_option.capacity_qtl then
                raise exception 'not enough capacity at %: % of % qtl already booked',
                        v_option.name, v_used, v_option.capacity_qtl
                    using errcode = 'P0001';
            end if;
        end if;
    end if;

    update public.logistics_bookings
       set status = p_new_status,
           notes  = coalesce(p_notes, notes)
     where id = p_booking_id
    returning * into v_booking;

    return row_to_json(v_booking)::jsonb;
end;
$$;

revoke all on function public.logistics_booking_update(uuid,text,text) from public, anon;
grant execute on function public.logistics_booking_update(uuid,text,text) to authenticated;

comment on function public.logistics_booking_update is
    'SECURITY DEFINER. Owner-only booking status transition with a proper '
    'state machine; notes are persisted (previously discarded).';

-- ─────────────────────────────────────────────────────────────────────────────
-- G. Audit trail: paid payment history must survive user deletion.
--    payments.user_id was ON DELETE CASCADE (008) — deleting a user silently
--    erased their paid payments.  RESTRICT forces explicit cleanup instead.
-- ─────────────────────────────────────────────────────────────────────────────
do $$
declare
    v_con text;
begin
    select c.conname into v_con
      from pg_constraint c
      join pg_class  t  on t.oid  = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      join pg_class  rt on rt.oid = c.confrelid
      join pg_namespace rn on rn.oid = rt.relnamespace
     where n.nspname = 'public' and t.relname = 'payments'
       and rn.nspname = 'public' and rt.relname = 'user_profiles'
       and c.contype = 'f'
       and (select array_agg(a.attname order by u.ordinality)
              from unnest(c.conkey) with ordinality as u(attnum, ordinality)
              join pg_attribute a on a.attrelid = c.conrelid and a.attnum = u.attnum)
           = '{user_id}';

    if v_con is not null then
        execute format('alter table public.payments drop constraint %I', v_con);
    end if;

    alter table public.payments
        add constraint payments_user_id_fkey
        foreign key (user_id) references public.user_profiles (id) on delete restrict;
end
$$;

comment on constraint payments_user_id_fkey on public.payments is
    'RESTRICT: payment history is an audit trail; deleting a user with payments must fail loudly.';

-- ─────────────────────────────────────────────────────────────────────────────
-- H. Dead-grant cleanup — least privilege for functions with no authenticated
--    caller (test_privileges.test_dead_control_check was structurally red).
--
--    nearest_market has no caller that runs as `authenticated` or `anon`
--    (it is used by the notifications job tier via the service-role client).
--    set_event_publication_date() is a BEFORE INSERT trigger helper on
--    events — it must not be directly executable by API roles at all.
--    review_event is deliberately kept for the admin JWT path (it gates on
--    has_role(admin) internally) and is tracked in the test's
--    KNOWN_VIOLATIONS ratchet until an events-review UI wires a caller.
--    has_role stays granted: RLS policies evaluate as the querying role.
-- ─────────────────────────────────────────────────────────────────────────────

revoke execute on function public.nearest_market(double precision, double precision)
    from public, anon, authenticated;
grant execute on function public.nearest_market(double precision, double precision)
    to service_role;

revoke execute on function public.set_event_publication_date()
    from public, anon, authenticated;
grant execute on function public.set_event_publication_date()
    to service_role;
