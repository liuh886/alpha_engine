# System Convergence Baseline 2026-09-09 (Phase 0)

`research_only=true`, `trade_ready=false`. Remeasure with the same protocol after each phase.

## 1. Inventory (measured 2026-09-09)

| Asset | Count |
|---|---|
| `configs/research_paradigms/*.yaml` active | 81 (+1 archived) |
| `configs/research_experiments/*.yaml` | 27 |
| `.github/workflows/*.yml` | 45 |
| `scripts/*.py` | 292 |
| `tests/**/*.py` | 498 |

## 2. Research entropy (sampled via reference graph)

- Strict exec orphans (no hit in `src/scripts/tests/.github/other configs`): **8/81 (~10%)**.
- Exec orphans incl. config-only references: **11/81 (~14%)**.
- Paradigms with no workflow schedule/dispatch: **66/81 (~81%)**; experiments: **24/27 (~89%)**.
- Governance: no TTL, no GC check, no CI ban on new `archive/` references. `check_ci_governance.py` covers tiers/triggers/action versions only. #858 handled manually.

## 3. Formal refresh health (last 10 runs, `formal-backtest-refresh.yml`)

- Fan-in `publish`: **0/10 green** (single market/strategy blockers fail the fan-in).
- Latest run (2026-09-09, head `c8ef7b48`): prepare/plan/providers-us/providers-cn green; strategies **4/5 green** (qqq, us_x, byd, cn_x); cn_27 red.
- cn_27 failure chain this week: 515180 vendor stall → provider-key gap for 5 off-pool names (fixed `c8ef7b48`) → restatement gate vs raw bars (fixed `2b432cc5c0`, verified 27/27 zero violations locally).

## 4. List-of-lists consistency (pre-Phase 1)

- Independent list sources: 7 (selected registry, 2 universes, reference registry, strategy pool + model pointer, dual-coded provider auxiliaries, benchmark constants, legacy US-23 pool).
- `overlap_count` / `strategy_specific_exceptions` are declarative integers; no code computes set intersection; `CONTRACT_PATHS` does not bind strategy files (cache-key blind spot).
- Provider auxiliaries are hand-written in two places (`formal_provider_cache.py:48`, `refresh_selected_pool_prices_v2.py:43`).

## 5. Evidence hash portability (spot check)

- Tracked CSVs sampled: 324; with CRLF bytes: **58** (sealed evidence preserved Windows-newlines, sha-bound).
- JSON canonicalization is inconsistent across modules (`ensure_ascii` True/False mixed; trailing-newline mixed).
- CSV writers have no unified `float_format`/column-order canonicalization; hashing is over raw bytes.
- Historical no-cutoff provider path uses `dump_all(lf_newlines=False)` (platform-dependent newlines).

## 6. Failure granularity (pre-Phase 2)

- Market-level熔断: v1 `failures -> rmtree + raise`; v2 `promotion_eligible=False` blocks `market_provider_cutoff` and the whole plan.
- Symbol-level isolation that exists: `retained_stale_source` (ready-source fetch failures), terminal-history retention, per-strategy job isolation (`fail-fast:false`).
- No symbol-level isolation: `extend_bars` / `_resolve_provider_keys` / `_check_manifest_symbol_health` raise on first bad symbol.

## 7. Narrow-loop readiness (pre-Phase 5)

- `model_data_bundle` training profiles cover US87/CN130/QQQI rotation; **no `us_small_pool` profile** → gate恒 `blocked` for the 23-name contract.
- `us_fundamental_acceleration` has factor-level sketch only; no frozen `research_experiments` spec with label/benchmark/cost/execution binding.
- No development/falsification backtest + supported/not-supported receipt for the narrow contract.

## Phase 3 addendum (2026-09-09)

- `dump_all` text calendars/instruments unified to LF (`lf_newlines=True` default; explicit `True` in `build_market_providers`). Linux CI bytes unchanged; Windows local rebuilds now match CI. Bins unaffected (binary).
- Verified: refresh `_write_csv` and `_stage_cutoff_source` already write LF; regression tests `tests/test_evidence_portability.py` lock LF output + dump determinism.
- Deliberately unchanged (recorded decision): sealed CRLF evidence keeps its bytes (re-hashing would break replay); per-module JSON canonical forms stay frozen (changing them would relabel live bundle ids); pandas float repr stays default (locked deps make it deterministic; rewriting bytes would invalidate sealed evidence for zero failing symptom).

## Phase 5 addendum (2026-09-09): first closed narrow loop

- Experiment `us_small_pool_fundamental_acceleration_v1`: **not_supported** (5 failed gates), evidence fully retained. Candidate trails equal-weight in both windows; SMA100 gate churns 7.8x/5.4x against a 4.0 ceiling; drawdown -0.41 breaches -0.35. No post-observation tuning performed.
- Determinism: 3 consecutive runs (incl. one LF rewrite) return identical verdict + metrics (dev 2.0884 / fals 0.6411).
- Training profile `us_small_pool_price_plus_fundamentals_v1`: prices green (23/23), fundamentals blocked at 0.609 < 0.80 with 9 named symbols — the gate correctly refuses model training. Corporate actions deliberately out of scope (adjusted bars + 40-session hold; no US store exists).
- Data-plane fixes landed along the way: WDC restatement first-seen PIT resolution; LF writers for the narrow chain (incl. pandas to_csv os.linesep trap); v1/v2 pool gates generalized with v2 defaults.
