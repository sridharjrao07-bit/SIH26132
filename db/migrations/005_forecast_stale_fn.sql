-- =============================================================================
-- Migration 005: mark_stale_forecasts function
--
-- Why is this needed?
-- When the engine runs, it UPSERTs rows for the next 7 days based on fresh
-- data. If a mandi stops reporting data, the engine will eventually refuse to
-- predict (returning 'insufficient_data'), but older predictions that were
-- previously written for future dates would remain as 'ok'.
-- 
-- This function identifies predictions that were generated more than `hours_old`
-- ago and marks them as 'stale'. This ensures farmers don't make decisions 
-- based on predictions that haven't incorporated recent real-world price movements.
--
-- The scheduler/backend can call this via Supabase RPC after each run or daily.
-- =============================================================================

create or replace function public.mark_stale_forecasts(hours_old integer default 24)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    stale_count integer;
begin
    update public.forecasts
    set status = 'stale'
    where status = 'ok'
      and generated_at < now() - (hours_old || ' hours')::interval;
      
    get diagnostics stale_count = row_count;
    return stale_count;
end;
$$;

-- Default grants hand EXECUTE to PUBLIC (incl. anon) — take it back:
revoke execute on function public.mark_stale_forecasts(integer) from public, anon;
grant  execute on function public.mark_stale_forecasts(integer) to service_role;
grant  execute on function public.mark_stale_forecasts(integer) to authenticated;

comment on function public.mark_stale_forecasts is 
'Marks forecasts as stale if they were generated more than hours_old ago (default 24). Prevents surfacing outdated predictions if ingestion stops.';
