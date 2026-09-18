-- =============================================================================
-- SIH26132 — Krishi Bazaar: Marketplace DB Invariants (PR-2)
-- Migration 031 — applies AFTER 030
--
-- Three categories of change in this migration:
--
-- A. PRIVILEGE REVOCATION
--    Direct INSERT/UPDATE/DELETE on workflow tables is revoked from the
--    `anon` and `authenticated` roles.  All mutations must go through ACID
--    transactional RPCs (031_marketplace_rpcs.sql).  This closes the
--    PostgREST-bypass gap: even a JWT-bearing user cannot write to these
--    tables directly through PostgREST — they must call an RPC which owns
--    the security invariants.
--
-- B. CONSTRAINT TRUTH
--    Database-level constraints that enforce relational invariants that were
--    previously "hoped-for" at the application layer:
--    - One accepted offer per lot at a time (unique partial index)
--    - Payment amount must equal price_per_qtl * quantity_qtl (not just > 0)
--    - buyers.verified can only be set to true via admin pathway
--    - lot status transitions are monotonic (no going back to 'open')
--
-- C. has_role_for() helper
--    A security-definer function that safely checks whether the calling
--    authenticated user has a given role without exposing user_profiles to
--    the anon role.
--
-- All changes are idempotent (IF NOT EXISTS / CREATE OR REPLACE / DROP IF
-- EXISTS before recreate) so the migration can be re-applied safely.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- A. PRIVILEGE REVOCATION
--    Revoke direct DML from PostgREST roles on workflow tables.
--    SELECT is preserved so GET endpoints still work via RLS.
--    All writes must go through RPCs defined in 031_marketplace_rpcs.sql.
-- ─────────────────────────────────────────────────────────────────────────────

-- buyers
revoke insert, update, delete on public.buyers from anon, authenticated;

-- lots
revoke insert, update, delete on public.lots from anon, authenticated;

-- offers
revoke insert, update, delete on public.offers from anon, authenticated;

-- payments
revoke insert, update, delete on public.payments from anon, authenticated;

-- bookings (if they exist — idempotent)
do $$
begin
    if exists (select 1 from information_schema.tables where table_schema='public' and table_name='storage_bookings') then
        revoke insert, update, delete on public.storage_bookings from anon, authenticated;
    end if;
    if exists (select 1 from information_schema.tables where table_schema='public' and table_name='logistics_bookings') then
        revoke insert, update, delete on public.logistics_bookings from anon, authenticated;
    end if;
end
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- B. CONSTRAINT TRUTH
-- ─────────────────────────────────────────────────────────────────────────────

-- B1. One accepted offer per lot
--     A buyer can be in 'accepted' state for a given lot at most once.
--     Without this, a race condition (two concurrent PATCH /offers/{id}/accept)
--     can double-accept, causing a payment to be raised twice.
create unique index if not exists idx_one_accepted_offer_per_lot
    on public.offers (lot_id)
    where status = 'accepted';

comment on index public.idx_one_accepted_offer_per_lot is
    'Prevents concurrent double-accept of offers for the same lot.';


-- B2. Payment amount must match the accepted offer
--     Replace the bare `amount > 0` check with a trigger that verifies
--     amount = offer.price_per_qtl * offer.quantity_qtl.
create or replace function public.check_payment_amount()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    v_expected numeric(12, 2);
begin
    select (price_per_qtl * quantity_qtl)::numeric(12, 2)
      into v_expected
      from public.offers
     where id = new.offer_id;

    if v_expected is null then
        raise exception 'PAYMENT_ORPHAN'
            using detail = 'offer_id % does not exist', hint = format('%s', new.offer_id);
    end if;

    if abs(new.amount - v_expected) > 0.01 then
        raise exception 'PAYMENT_AMOUNT_MISMATCH'
            using detail = format(
                'payment.amount=%s does not match offer.price_per_qtl * offer.quantity_qtl=%s',
                new.amount, v_expected
            );
    end if;

    return new;
end;
$$;

drop trigger if exists trg_check_payment_amount on public.payments;
create trigger trg_check_payment_amount
    before insert on public.payments
    for each row execute function public.check_payment_amount();

comment on function public.check_payment_amount() is
    'Enforces payment.amount = offer.price_per_qtl * offer.quantity_qtl at the DB boundary.';


-- B3. Lot status monotonicity — prevent rolling back from sold/withdrawn
--     Status must move forward: open → offered → matched → sold | withdrawn.
--     The trigger raises on attempts to regress (e.g. sold → open).
create or replace function public.guard_lot_status_regression()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    -- Ordinal weight: higher = later in lifecycle
    v_weights  json := '{"open":0,"offered":1,"matched":2,"sold":3,"withdrawn":3}';
    v_old_w    int;
    v_new_w    int;
begin
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

drop trigger if exists trg_guard_lot_status_regression on public.lots;
create trigger trg_guard_lot_status_regression
    before update on public.lots
    for each row
    when (old.status is distinct from new.status)
    execute function public.guard_lot_status_regression();

comment on function public.guard_lot_status_regression() is
    'Prevents lot.status from regressing to an earlier lifecycle state.';


-- B4. buyers.verified — prevent direct self-verification
--     An authenticated role cannot flip their own verified flag.
--     Verification must go through an admin RPC (buyer_verify).
create or replace function public.guard_buyer_self_verify()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    -- Allow service_role (used by admin RPCs) to change verified freely.
    if current_setting('role') = 'service_role' then
        return new;
    end if;

    -- Block any non-service_role from changing verified.
    if old.verified is distinct from new.verified then
        raise exception 'BUYER_SELF_VERIFY_FORBIDDEN'
            using detail = 'buyers.verified can only be changed by an admin RPC';
    end if;

    return new;
end;
$$;

drop trigger if exists trg_guard_buyer_self_verify on public.buyers;
create trigger trg_guard_buyer_self_verify
    before update on public.buyers
    for each row
    when (old.verified is distinct from new.verified)
    execute function public.guard_buyer_self_verify();

comment on function public.guard_buyer_self_verify() is
    'Prevents direct self-verification of buyers; requires service_role (admin RPC path).';


-- ─────────────────────────────────────────────────────────────────────────────
-- C. has_role_for() — safe role check for use inside RPCs
--    Unlike has_role() which relies on user_profiles being readable by the
--    calling role, has_role_for() runs as SECURITY DEFINER so it works even
--    when caller is `authenticated` and user_profiles is locked down.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.has_role_for(p_user_id uuid, p_role text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
          from public.user_profiles
         where id = p_user_id
           and role = p_role
    );
$$;

-- Restrict to authenticated and service_role — anon must never call this.
revoke execute on function public.has_role_for(uuid, text) from public, anon;
grant  execute on function public.has_role_for(uuid, text) to authenticated, service_role;

comment on function public.has_role_for(uuid, text) is
    'Returns true if user p_user_id has role p_role. Runs as security definer '
    'so it works inside RPCs where user_profiles may not be directly accessible.';
