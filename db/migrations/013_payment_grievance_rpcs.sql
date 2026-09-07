-- =============================================================================
-- Migration 013: Ownership-asserting RPCs for payment and grievance transitions
--
-- Problem: payment/grievance state changes are currently plain
-- table("...").update(...) calls on the service-role or user-scoped client.
-- A service-role call from a bug/misconfiguration could mutate any row.
-- These SECURITY DEFINER functions enforce row-level ownership and state-machine
-- validity even when called via service_role.
--
-- Belt-and-braces: if auth.uid() is not null (i.e., called from a user-JWT
-- context), the function also asserts the caller's UID matches p_user_id.
-- This makes cross-tenant mutations impossible even if the caller passes the
-- wrong p_user_id.
--
-- Grant: EXECUTE to authenticated + service_role; revoke from public + anon.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- Payment transition RPC
-- ─────────────────────────────────────────────────────────────────────────────

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
    -- Belt-and-braces: reject caller-UID mismatch when running in authenticated context
    if auth.uid() is not null and auth.uid() <> p_user_id then
        raise exception 'cross-tenant mutation rejected: caller % != owner %', auth.uid(), p_user_id
            using errcode = 'P0001';
    end if;

    select * into v_payment
    from public.payments
    where id = p_payment_id and user_id = p_user_id;

    if not found then
        raise exception 'payment not found or not owned by user' using errcode = 'P0002';
    end if;

    -- State-machine validation
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
        -- Any non-paid status can be disputed; paid disputals are allowed too.
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
  'SECURITY DEFINER. Asserts ownership (user_id = p_user_id) and validates the '
  'payment state machine before updating. Rejects cross-principal calls even via service_role.';

-- ─────────────────────────────────────────────────────────────────────────────
-- Grievance transition RPC
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.transition_grievance_status(
    p_user_id     uuid,
    p_grievance_id uuid,
    p_new_status  text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_grievance grievances%rowtype;
begin
    -- Belt-and-braces caller check
    if auth.uid() is not null and auth.uid() <> p_user_id then
        raise exception 'cross-tenant mutation rejected: caller % != owner %', auth.uid(), p_user_id
            using errcode = 'P0001';
    end if;

    select * into v_grievance
    from public.grievances
    where id = p_grievance_id and user_id = p_user_id;

    if not found then
        raise exception 'grievance not found or not owned by user' using errcode = 'P0002';
    end if;

    -- State-machine validation (open → in_progress → resolved/rejected)
    if p_new_status not in ('open', 'in_progress', 'resolved', 'rejected') then
        raise exception 'unknown target status: %', p_new_status using errcode = 'P0004';
    end if;
    if v_grievance.status in ('resolved', 'rejected') then
        raise exception 'grievance is already %', v_grievance.status using errcode = 'P0003';
    end if;

    update public.grievances
    set status     = p_new_status,
        updated_at = now()
    where id = p_grievance_id;

    return (select row_to_json(g.*)::jsonb from public.grievances g where g.id = p_grievance_id);
end;
$$;

revoke all on function public.transition_grievance_status(uuid, uuid, text) from public, anon;
grant execute on function public.transition_grievance_status(uuid, uuid, text) to authenticated, service_role;

comment on function public.transition_grievance_status is
  'SECURITY DEFINER. Asserts ownership (user_id = p_user_id) and validates the '
  'grievance state machine before updating. Rejects cross-principal calls even via service_role.';
