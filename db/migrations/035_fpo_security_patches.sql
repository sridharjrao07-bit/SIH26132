-- db/migrations/035_fpo_security_patches.sql
-- Hotfix: re-applies the two security-critical function bodies changed in 032.
-- 032 is already in schema_migrations on existing DBs so would be skipped;
-- this migration ensures live databases get the fixes without a full rebuild.
--
-- FIX 1 (P0-2 NULL hole): lots.fpo_id is nullable (008:119, on delete set null).
--   `v_lot.fpo_id != v_user_id` evaluates to NULL for individual-farmer lots,
--   so the IF is not taken and the lot is silently accepted. IS DISTINCT FROM fixes.
--
-- FIX 7 (P1-3): lot_create must verify the caller is actually a member of the
--   FPO they attribute a lot to. Without this, any authenticated user can set
--   fpo_id = any UUID they know.

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

        -- NULL-safe: lots.fpo_id is nullable (008_marketplace.sql:119, on delete set null).
        -- Plain `!=` evaluates to NULL for farmer lots (fpo_id IS NULL), so the IF is
        -- never taken and the lot is silently accepted. IS DISTINCT FROM returns TRUE.
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

-- grants preserved from 032 (create or replace keeps them, but explicit is safer)
revoke all on function public.fpo_aggregate_lots(uuid[],uuid,numeric) from public, anon;
grant execute on function public.fpo_aggregate_lots(uuid[],uuid,numeric) to authenticated;

-- P1-3 patch: re-create lot_create with membership guard on p_fpo_id.
-- See 032_marketplace_rpcs.sql for full function body; only the guard block is new.
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

    -- P1-3: a caller may only attribute a lot to an FPO they actually belong to.
    if p_fpo_id is not null
       and p_fpo_id is distinct from v_user_id
       and not exists (
            select 1 from public.fpo_members
             where fpo_id    = p_fpo_id
               and member_id = v_user_id
       ) then
        raise exception 'lot_create: caller is not a member of FPO %', p_fpo_id
            using errcode = 'P0001';
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
