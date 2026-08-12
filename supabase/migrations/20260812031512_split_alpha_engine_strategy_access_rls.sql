drop policy if exists "Strategy current operations follow runtime access policy"
on public.strategy_operation_snapshots;

create policy "Public strategy current operations"
on public.strategy_operation_snapshots
for select
to anon, authenticated
using (
  exists (
    select 1
    from public.product_access_policies p
    where p.product_code = 'alpha_engine'
      and p.resource_type = 'strategy'
      and p.resource_id = strategy_operation_snapshots.strategy_id
      and p.required_tier = 'public'
  )
);

create policy "Authenticated strategy current operations"
on public.strategy_operation_snapshots
for select
to authenticated
using (
  exists (
    select 1
    from public.product_access_policies p
    where p.product_code = 'alpha_engine'
      and p.resource_type = 'strategy'
      and p.resource_id = strategy_operation_snapshots.strategy_id
      and (
        p.required_tier = 'authenticated'
        or (
          p.required_tier = 'pro'
          and (
            (((select auth.jwt()) -> 'app_metadata' ->> 'alpha_engine_role') = 'owner')
            or exists (
              select 1
              from public.entitlements e
              where e.user_id = (select auth.uid())
                and e.entitlement_code = 'alpha_engine.pro'
                and e.active is true
                and (e.valid_until is null or e.valid_until > now())
            )
          )
        )
        or (
          p.required_tier = 'owner'
          and (((select auth.jwt()) -> 'app_metadata' ->> 'alpha_engine_role') = 'owner')
        )
      )
  )
);
