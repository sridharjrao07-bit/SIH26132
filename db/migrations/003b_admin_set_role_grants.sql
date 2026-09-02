-- 003b_admin_set_role_grants.sql
-- Run after 003. EXECUTE stays on service_role only (F-015).
-- Admins elevate via the SQL editor, not a PostgREST-callable grant to authenticated.

revoke execute on function public.admin_set_role(uuid, text) from public, anon, authenticated;
grant execute on function public.admin_set_role(uuid, text) to service_role;
