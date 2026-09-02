-- 003b_admin_set_role_grants.sql
-- Run after 003 to allow authenticated admins to use the function

grant execute on function public.admin_set_role(uuid, text) to authenticated;
grant execute on function public.admin_set_role(uuid, text) to service_role;
