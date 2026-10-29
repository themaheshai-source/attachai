-- Restrict audit rows to a concrete tenant claim. NULL-client rows are global/admin
-- records and must not be exposed through tenant RLS. Service-role backend access
-- remains available under Supabase's service-role RLS bypass.
drop policy if exists audit_tenant on public.audit_logs;
create policy audit_tenant on public.audit_logs
  for all
  using (client_id is not null and client_id = app_tenant_id())
  with check (client_id is not null and client_id = app_tenant_id());
