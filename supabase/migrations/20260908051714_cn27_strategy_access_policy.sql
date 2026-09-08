-- CN27 V1.3 formal baseline: declare the runtime access tier for cn_27
-- current operations.
--
-- Siblings us_x / cn_x / byd are public and the strategy registry declares
-- cn_27 historical evidence public, so cn_27 follows at public. The publish
-- edge function fails closed with HTTP 400 for any catalog strategy without
-- a row here, which blocked `alpha ops publish` after the CN27 baseline
-- merge. Tier changes remain owner-managed via /settings/access; no code
-- change is needed to raise or lower this tier later.

insert into public.product_access_policies (
  product_code, resource_type, resource_id, required_tier, updated_by, updated_at
) values
  ('alpha_engine', 'strategy', 'cn_27', 'public', null, now())
on conflict (product_code, resource_type, resource_id)
do update set
  required_tier = excluded.required_tier,
  updated_by = excluded.updated_by,
  updated_at = excluded.updated_at;
