-- 043_resolve_gen_random_bytes.sql
--
-- Let the direct-channel RPCs reach gen_random_bytes without editing 039.
--
-- WHY THIS EXISTS
-- Migration 039 created direct_plan_commit with `set search_path = public` and
-- an unqualified gen_random_bytes(12) call. 042 now puts pgcrypto in the
-- `extensions` schema, which makes the unqualified call fail to resolve.
--
-- 039 has already been applied to the live database. Editing it is not an
-- option: schema_migrations records filenames, not checksums, so an edited 039
-- never re-runs there, and the file would describe a migration that did not
-- happen. This file is the forward-only correction.
--
-- WHAT IT DOES
-- Creates public.gen_random_bytes as a thin delegating wrapper. Inside
-- direct_plan_commit the unqualified call now resolves through search_path to
-- this wrapper, which crosses into the extensions schema.
--
-- WHY A WRAPPER RATHER THAN RE-DECLARING THE FUNCTION
-- Re-declaring direct_plan_commit here would duplicate ~200 lines of SQL, and
-- the copy would silently go stale the next time the function is edited in 039.
-- A wrapper is six lines and has nothing to drift. It is safe to shadow the
-- name in `public` precisely because 042 guarantees pgcrypto is in
-- `extensions`, not `public` -- so there is no pgcrypto function here to
-- clobber.
--
-- Idempotent: create or replace is a no-op on re-run.
-- =============================================================================

begin;

create or replace function public.gen_random_bytes(bits integer)
returns bytea
language sql
security definer
set search_path = extensions
as $$
    select extensions.gen_random_bytes(bits)
$$;

-- Deliberately not granted to anon: this exists so security-definer RPCs can
-- mint tokens, not so clients can generate randomness themselves.
revoke all on function public.gen_random_bytes(integer) from public;
grant execute on function public.gen_random_bytes(integer) to authenticated, service_role;

comment on function public.gen_random_bytes(integer) is
    'Delegates to extensions.gen_random_bytes so RPCs running with '
    'search_path = public can mint trace tokens. Added by migration 043; see '
    '042 for why pgcrypto lives in the extensions schema.';

commit;
