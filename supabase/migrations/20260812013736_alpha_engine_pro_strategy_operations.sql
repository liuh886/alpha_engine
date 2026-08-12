create table public.strategy_operation_snapshots (
  strategy_id text primary key,
  model_version_id text not null,
  required_entitlement text not null,
  source_fingerprint text not null,
  snapshot jsonb not null,
  updated_at timestamptz not null default now(),
  constraint strategy_operation_snapshot_identity check (snapshot ->> 'strategy_id' = strategy_id),
  constraint strategy_operation_model_identity check (snapshot ->> 'model_version_id' = model_version_id),
  constraint strategy_operation_research_only check ((snapshot ->> 'research_only')::boolean is true),
  constraint strategy_operation_not_trade_ready check ((snapshot ->> 'trade_ready')::boolean is false)
);

comment on table public.strategy_operation_snapshots is
  'Protected current strategy-operation snapshots. Historical formal evidence remains public; rows here require an active product entitlement.';

alter table public.strategy_operation_snapshots enable row level security;

revoke all on table public.strategy_operation_snapshots from public, anon, authenticated;
grant select on table public.strategy_operation_snapshots to authenticated;

create policy "Entitled users read protected strategy operations"
on public.strategy_operation_snapshots
for select
to authenticated
using (
  (((select auth.jwt()) -> 'app_metadata' ->> 'alpha_engine_role') = 'owner')
  or exists (
    select 1
    from public.entitlements e
    where e.user_id = (select auth.uid())
      and e.entitlement_code = strategy_operation_snapshots.required_entitlement
      and e.active is true
      and (e.valid_until is null or e.valid_until > now())
  )
);

delete from public.product_access_policies
where product_code = 'alpha_engine'
  and resource_type = 'model'
  and resource_id = 'qqq_rotation';

insert into public.strategy_operation_snapshots (
  strategy_id,
  model_version_id,
  required_entitlement,
  source_fingerprint,
  snapshot
) values (
  'qqq_rotation',
  'qqqi_qqq_tqqq_v4_3',
  'alpha_engine.pro',
  '6260a294e1869a128922',
  $snapshot${
    "strategy_id":"qqq_rotation",
    "model_version_id":"qqqi_qqq_tqqq_v4_3",
    "current_operations_access":"pro",
    "status":"current_no_change",
    "as_of":"2026-08-10",
    "latest_completed_session":"2026-08-10",
    "decision_cadence":"Every completed US market session",
    "next_decision_policy":"Evaluate at close; target applies to the next eligible open.",
    "state_label":"Transition · formal_state_allocation",
    "decision_reason":"formal_state_allocation → formal_state_allocation",
    "allocations":[
      {"asset":"QQQ","current":0.5,"target":0.5,"delta":0.0},
      {"asset":"QQQI","current":0.5,"target":0.5,"delta":0.0},
      {"asset":"SGOV","current":0.0,"target":0.0,"delta":0.0},
      {"asset":"TQQQ","current":0.0,"target":0.0,"delta":0.0}
    ],
    "turnover":0.0,
    "estimated_cost":0.0,
    "data_freshness":"current",
    "factor_freshness":"current",
    "delivery_status":"not_required",
    "source_label":"Governed QQQ signal ledger",
    "source_href":null,
    "note":"Latest governed evaluation retained the existing allocation.",
    "factor_evidence":[
      {"factor_id":"strategy.qqq.vix_close","factor_version":"1.0","implementation_hash":"d71008f4870da95f426257b0c17b78e0943fe9122783260101f51347fb7b817d","display_name":"VIX close","information_family":"volatility","value":15.460000038146973,"reference":{"normal":null,"stress":null},"state":"calm","effect":"veto","reason_code":"vix_easing_supports_release","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.vxn_close","factor_version":"1.0","implementation_hash":"c945dabaef82f50af15bb214da45e7bc706632b14289cfa4525d2d85b52c193c","display_name":"VXN close","information_family":"volatility","value":23.040000915527344,"reference":{"normal":null,"stress":null},"state":"calm","effect":"neutral","reason_code":"vxn_neutral","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.qqq_vs_ma20","factor_version":"1.0","implementation_hash":"acdb7eea6c3f40c76e53a937f12136069a7389e3ace298b860a03901949ef3a1","display_name":"QQQ distance to SMA20","information_family":"trend","value":0.028644569889097582,"reference":0.0,"state":"at_or_above","effect":"veto","reason_code":"price_repair_supports_release","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.qqq_vs_ma200","factor_version":"1.0","implementation_hash":"8ec5a93cdb620aab795f0092b0041692142e16810621509a4a21c88203612da5","display_name":"QQQ distance to SMA200","information_family":"trend","value":0.11371819106523073,"reference":0.0,"state":"above_long_trend","effect":"neutral","reason_code":"long_trend_intact","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.rsi14","factor_version":"1.0","implementation_hash":"25b9d2baa3862b01d34e78576394e139989cf889643fce7b8329b31e9a9eee60","display_name":"RSI(14)","information_family":"momentum","value":56.211114857951195,"reference":30.0,"state":"normal","effect":"neutral","reason_code":"rsi_not_panic","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.fear_greed","factor_version":"1.0","implementation_hash":"52cb49acbbe7b750bdb84504fd6be4d821469c1d3f53bbc166008030ff9242ae","display_name":"Fear & Greed","information_family":"sentiment","value":64.3714285714286,"reference":10.0,"state":"normal","effect":"neutral","reason_code":"fear_greed_not_extreme","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.ma200_falling","factor_version":"1.0","implementation_hash":"7a2c3d06b1f5683199c19161f596e0f2ae9201f0a0977fee609aa0839ea73f5b","display_name":"SMA200 falling","information_family":"trend_state","value":false,"reference":false,"state":"not_falling","effect":"neutral","reason_code":"ma200_not_falling","observed_at":"2026-08-10"},
      {"factor_id":"strategy.qqq.strong_defense","factor_version":"1.0","implementation_hash":"7cbbd3045eae0a1b20a40c7227850803ac86eeae76ebce01f19a8c6487b90302","display_name":"Strong defense active","information_family":"rule_state","value":false,"reference":false,"state":"inactive","effect":"neutral","reason_code":"strong_defense_inactive","observed_at":"2026-08-10"}
    ],
    "source_identity":{
      "formal_bundle_id":"2f588e219a851c839fc087e27be163739f811c7691cd7d109795ab9e226957c8",
      "formal_run_id":"qqqi_qqq_tqqq_v4_3-through-2026_08_07",
      "formal_evidence_cutoff":"2026-08-07",
      "ledger_fingerprint":"6260a294e1869a128922",
      "signal_sha256":"cd640cabc28585c87a726768ce387a4ab39b8eba8db93e1175763e3c620f3e73",
      "factor_catalog_implementation_hash":"6c63fb7954b316632f30dc46bbafba7740c32fdc42abe3202774a6f56274b2f4",
      "workflow_run_id":"31458352843",
      "commit_sha":"af74ca84055bbc2ae9d1cb53a12c824905554e1e",
      "github_issue_number":null
    },
    "research_only":true,
    "trade_ready":false
  }$snapshot$::jsonb
);
