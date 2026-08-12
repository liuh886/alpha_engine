create table if not exists public.product_access_policies (
  product_code text not null,
  resource_type text not null check (resource_type in ('model', 'module')),
  resource_id text not null,
  required_tier text not null check (required_tier in ('public', 'authenticated', 'pro', 'owner')),
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (product_code, resource_type, resource_id)
);

comment on table public.product_access_policies is
  'Owner-managed minimum access tier for independent product modules. Strategy current-operation access is governed by each product strategy catalog.';

alter table public.product_access_policies enable row level security;

revoke all on table public.product_access_policies from public, anon, authenticated;
grant select on table public.product_access_policies to anon, authenticated;
grant insert, update, delete on table public.product_access_policies to authenticated;

drop policy if exists "Access policies are readable" on public.product_access_policies;
create policy "Access policies are readable"
on public.product_access_policies
for select
to anon, authenticated
using (true);

drop policy if exists "AlphaEngine Owner can insert access policies" on public.product_access_policies;
create policy "AlphaEngine Owner can insert access policies"
on public.product_access_policies
for insert
to authenticated
with check (
  product_code = 'alpha_engine'
  and updated_by = (select auth.uid())
  and (select auth.jwt() -> 'app_metadata' ->> 'alpha_engine_role') = 'owner'
);

drop policy if exists "AlphaEngine Owner can update access policies" on public.product_access_policies;
create policy "AlphaEngine Owner can update access policies"
on public.product_access_policies
for update
to authenticated
using (
  product_code = 'alpha_engine'
  and (select auth.jwt() -> 'app_metadata' ->> 'alpha_engine_role') = 'owner'
)
with check (
  product_code = 'alpha_engine'
  and updated_by = (select auth.uid())
  and (select auth.jwt() -> 'app_metadata' ->> 'alpha_engine_role') = 'owner'
);

drop policy if exists "AlphaEngine Owner can delete access policies" on public.product_access_policies;
create policy "AlphaEngine Owner can delete access policies"
on public.product_access_policies
for delete
to authenticated
using (
  product_code = 'alpha_engine'
  and (select auth.jwt() -> 'app_metadata' ->> 'alpha_engine_role') = 'owner'
);

insert into public.product_access_policies (product_code, resource_type, resource_id, required_tier)
values
  ('alpha_engine', 'module', 'securities', 'authenticated')
on conflict (product_code, resource_type, resource_id) do nothing;
