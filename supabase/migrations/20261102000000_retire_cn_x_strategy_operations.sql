-- Retire legacy cn_x strategy from current operations runtime.
--
-- CN_27 V1.3 replaced CN x1.2 as the accepted formal CN strategy (ADR-0003).
-- Remove the retired cn_x strategy snapshot and product access policy row so
-- the runtime access plane only exposes the 4 maintained active strategies
-- (byd, qqq_rotation, us_x, cn_27).
--
-- Historical research packages and sealed artifacts in data/research remain
-- unchanged for reproducibility and forensic continuity.

delete from public.strategy_operation_snapshots
where strategy_id = 'cn_x';

delete from public.product_access_policies
where product_code = 'alpha_engine'
  and resource_type = 'strategy'
  and resource_id = 'cn_x';
