alter table public.product_access_policies
  drop constraint if exists product_access_policies_resource_type_check;

alter table public.product_access_policies
  add constraint product_access_policies_resource_type_check
  check (resource_type = any (array['strategy'::text, 'module'::text]));

comment on table public.product_access_policies is
  'Owner-managed minimum access tier for AlphaEngine strategy current operations and independent product modules.';

delete from public.product_access_policies
where product_code = 'alpha_engine'
  and resource_type = 'model';

insert into public.product_access_policies (
  product_code, resource_type, resource_id, required_tier, updated_by, updated_at
) values
  ('alpha_engine', 'strategy', 'qqq_rotation', 'pro', null, now()),
  ('alpha_engine', 'strategy', 'us_x', 'public', null, now()),
  ('alpha_engine', 'strategy', 'cn_x', 'public', null, now()),
  ('alpha_engine', 'strategy', 'byd', 'public', null, now())
on conflict (product_code, resource_type, resource_id)
do update set
  required_tier = excluded.required_tier,
  updated_by = excluded.updated_by,
  updated_at = excluded.updated_at;

drop policy if exists "Entitled users read protected strategy operations"
on public.strategy_operation_snapshots;

alter table public.strategy_operation_snapshots
  drop column if exists required_entitlement;

revoke all on table public.strategy_operation_snapshots from public, anon, authenticated;
grant select on table public.strategy_operation_snapshots to anon, authenticated;

create policy "Strategy current operations follow runtime access policy"
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
      and (
        p.required_tier = 'public'
        or (
          p.required_tier = 'authenticated'
          and (select auth.uid()) is not null
        )
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

comment on table public.strategy_operation_snapshots is
  'Runtime current strategy-operation snapshots. Row visibility is governed by product_access_policies keyed by stable strategy_id.';
