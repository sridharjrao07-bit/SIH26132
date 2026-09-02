-- =============================================================================
-- Migration 007: Security Hardening
--
-- 1. job_locks: Enable RLS (deny-all default) + explicit privilege tightening
-- 2. mark_stale_forecasts: Revoke EXECUTE from authenticated
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- S1: job_locks — enable RLS + belt-and-braces privilege revoke
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable deny-all RLS. No policies added: the RPCs claim_job_lock and
-- release_job_lock (already service_role–only) are the only legitimate callers.
ALTER TABLE public.job_locks ENABLE ROW LEVEL SECURITY;

-- Strip any default public/anon/authenticated table privileges so the
-- PostgREST REST endpoint returns 403 before even evaluating RLS.
REVOKE ALL ON public.job_locks FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.job_locks TO service_role;

-- ─────────────────────────────────────────────────────────────────────────────
-- S2: mark_stale_forecasts — revoke EXECUTE from authenticated
--
-- This is a SECURITY DEFINER function that performs an unrestricted UPDATE on
-- the forecasts table. Any farmer with a valid JWT could call it via
-- POST /rest/v1/rpc/mark_stale_forecasts and invalidate the entire forecast
-- table. Only service_role (the scheduler/admin path) should be able to call it.
-- service_role EXECUTE was already granted in 005_forecast_stale_fn.sql.
-- ─────────────────────────────────────────────────────────────────────────────

REVOKE EXECUTE ON FUNCTION public.mark_stale_forecasts(integer) FROM authenticated;

-- ─────────────────────────────────────────────────────────────────────────────
-- Defense-in-depth note for future contributors
-- ─────────────────────────────────────────────────────────────────────────────

-- The following tables have RLS enabled with SELECT-only policies for
-- anon/authenticated (see 001_schema.sql + 003_security_patch.sql):
--   markets, commodities, forecasts, commodity_alias, prices, alerts,
--   user_profiles, notification_log, ingestion_log
--
-- INSERT/UPDATE/DELETE have no permissive policies on these tables, meaning
-- they are DENIED by default while RLS is active.
--
-- DO NOT add a "using(true)" or "with check(true)" write policy on any of
-- these tables without an explicit admin security review. Writes go through
-- the service_role client (background jobs) or user-scoped clients (alerts
-- only, where an ownership policy already exists).

COMMENT ON TABLE public.job_locks IS
  'Distributed locks for cron jobs. RLS enabled (deny-all). '
  'Access only via claim_job_lock / release_job_lock RPCs (service_role only). '
  'Direct table access for anon/authenticated is revoked.';
