-- Owner scope, 2026-11-08: public Preview is historical evidence + sanitized
-- system status only. Existing current-operation rows must never be anonymous.
-- This changes access controls, not frozen evidence, signals or strategy math.
begin;

revoke select on public.strategy_operation_snapshots from anon;

insert into public.product_access_policies
  (product_code, resource_type, resource_id, required_tier)
values
  ('alpha_engine', 'strategy', 'byd', 'pro'),
  ('alpha_engine', 'strategy', 'cn_27', 'pro'),
  ('alpha_engine', 'strategy', 'qqq_rotation', 'pro'),
  ('alpha_engine', 'strategy', 'us_x', 'pro')
on conflict (product_code, resource_type, resource_id) do update
set required_tier = case
  when product_access_policies.required_tier = 'owner' then 'owner'
  else 'pro'
end;

-- A restrictive floor composes with the existing tier policies. Even a later
-- accidental public-tier edit cannot reopen anonymous/non-entitled reads.
-- The active IDs match the existing publisher allowlist and canonical registry.
drop policy if exists "Current operations minimum entitlement"
on public.strategy_operation_snapshots;
create policy "Current operations minimum entitlement"
on public.strategy_operation_snapshots
as restrictive
for select
to anon, authenticated
using (
  (select auth.uid()) is not null
  and strategy_id in ('byd', 'cn_27', 'qqq_rotation', 'us_x')
  and (
    (((select auth.jwt()) -> 'app_metadata' ->> 'alpha_engine_role') = 'owner')
    or exists (
      select 1 from public.entitlements e
      where e.user_id = (select auth.uid())
        and e.entitlement_code = 'alpha_engine.pro'
        and e.active is true
        and (e.valid_until is null or e.valid_until > now())
    )
  )
);

commit;
