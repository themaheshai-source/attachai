-- Atomic allowlist replacement for the service-role-backed Python API.
-- This avoids losing all allowed domains when a multi-request REST update fails.
create or replace function public.replace_client_domains(p_client_id uuid, p_domains text[])
returns void
language plpgsql
set search_path = public
as $$
begin
  delete from public.domains where client_id = p_client_id;
  insert into public.domains(client_id, domain)
  select p_client_id, distinct_domain
  from (
    select distinct trim(u.domain_value) as distinct_domain
    from unnest(coalesce(p_domains, array[]::text[])) as u(domain_value)
  ) values_to_add
  where distinct_domain <> ''
  on conflict (client_id, domain) do nothing;
end;
$$;

revoke all on function public.replace_client_domains(uuid, text[]) from public, anon, authenticated;
grant execute on function public.replace_client_domains(uuid, text[]) to service_role;
