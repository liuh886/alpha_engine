# Convergence Gap Report — 2026-09-19

Status: research evidence, `research_only=true`, `trade_ready=false`
Authority: this report owns the *remaining-work backlog and gap-to-target* view.
It does not replace issue #1074 (prioritization), #324/#325 (data closure),
#826 (training plane) or the frozen contracts it references.

## 1. Purpose

Record, in one place, (a) what was completed in the 2026-09-19 convergence
cycle, (b) exactly what remains, and (c) the distance between the current
system and the target end state. Each remaining item has an explicit
acceptance test so "done" cannot be claimed from implementation alone.

## 2. Target end state (from #1074)

```text
Market Data -> Governed Data Bundle -> Research / Training -> Evidence Bundle
  -> Promotion Decision -> Active Strategy Registry -> Strategy Runtime
  -> Decision Ledger -> Strategy Operations -> Console / Notification
```

One authority per layer. Superseded paths are deleted, not retained as
fallback or migration layers. Effort allocation in #1074: daily operations 35%,
delete/converge 25%, #324/#325 data closure 20%, #826 training plane 10%,
dependency/security/governance 10%, new models/factors/dashboard ~0%.

## 3. Verified baseline after this cycle

| Gate | Result |
| --- | --- |
| `ruff check .` | pass |
| `mypy` ratcheted scope | pass (11 files: `src/release`, `scripts/release_gate.py`, `src/models/metric_contract.py`, `src/research/{economics,replay_comparison,ranker_execution,ranker_training,us_x1_3_current_target}.py`, `src/data/listing_lifecycle.py`) |
| `pytest tests -q --strict-markers` | 3803 passed, 8 approved skips |
| `tsc --noEmit` / `eslint` / `vitest` | pass / pass / 158 passed |
| `npm run build` | pass (single-file static PWA) |
| `npx playwright test` | 34 passed, 2 skipped |
| `scripts/doctor.py` | environment healthy |
| `check_ci_governance --enforce` | 0 violations |
| `dead_modules` advisory | **85 of 527** tracked `src/research`+`scripts` modules have no live caller |
| `.git` garbage | 0 (was 96.55 MiB) |

Completed this cycle (see git log): test-registry isolation + `make ci` repair
(`1f672cfa`); chart drawdown provenance (#1112, `442ccac6`); QQQ/QQQI v4.x
runner removal (`20bd1cb2`); QQQ paradigm archival (`1d8b5cb5`); weekly
health-gate auto-close (`d106513b`); governed terminal-listing selection gate
(#1113 code half, `752d0e44`); strict-mypy ratchet (`e3cefd7e`); advisory
dead-module inventory (`a545dc0de`); governance/release doc sync (`6246553c`);
scratch-script removal (`28942fe9`).

## 4. Remaining work and gap-to-target

| ID | Workstream | Authority | Current state | Gap to target | Acceptance (definition of done) | Prerequisite | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | Daily operation closure | #1074 §1, #1113 | code guard landed; refresh blocked at `EA/2026-09-11` | committed 2026-09-11 US x1.3 target is inconsistent with the corrected provider | a governed regeneration of that current target on the corrected provider, ledger re-sealed, then the next eligible session's formal refresh completes with no unexplained blocker | provider environment + governed regen run | medium |
| G2 | US87/CN130 PIT event + fundamental closure | #1074 §3, #324 | readiness (`data/research/model_data_bundle_v1/model-data-readiness.json`, built 2026-09-18): prices/actions ready; `fundamentals.cn` **partial** 129/130 ( `301666` provider_missing); `fundamentals.us` **partial** 86/87 (`SBGSY` identity_missing); `us_selected_price_plus_fundamentals_v1` ready, `us_small_pool_price_plus_fundamentals_v1` blocked | close the two per-symbol PIT gaps and lift the blocked profile | `fundamentals.*` components ready; `us_small_pool_price_plus_fundamentals_v1` unblocked; 0 blocked components | provider data (`301666` CN report source; `SBGSY` US identity) | high |
| G3 | Canonical Alpha158 panel | #1074 §3, #325 | `factors.qlib_alpha158.panel.cn.v1` **partial** 129/130 (`301666` not_yet_applicable); `us_selected_alpha158_v1` **blocked** | materialize exact US87 Alpha158 panel with governed VWAP semantics | `us_selected_alpha158_v1` training profile ready | provider data + factor materialization; shares the `301666` gap with G2 | high |
| G4 | Canonical training plane | #1074 §4, #826 | not started | one reproducible trainer reproduces US x1.2 `r11_sampled` from immutable inputs | deterministic trained artifact + score trace; incumbent economic replay blocks candidate ranking | G2, G3 | high |
| G5 | Obsolete-path removal / convergence | #1074 §2, #858 | 85 unreferenced modules, 45 workflows (36 tier-3), 63 active paradigms | delete/archive superseded paths per family; converge CI | `dead_modules` advisory converges to zero for non-authority code; workflow count reduced with canonical replacement, not wrappers | owner approval per family | medium |
| G6 | Static-check ratchet | #1074 §5 | strict mypy scope now **25 entries (24 files + `src/release/`)** in `pyproject.toml` + `ci.yml` after the 2026-09-20 session; ruff `E,F` only | ratchet remaining canonical runtime/research modules; add ruff rules | CI-enforced typed scope covers the canonical runtime and research modules | per-module typing fixes; **next**: `cn_x1_2_current_target` protocol debt (`CrossSectionalExperimentSpec` vs `RankerExperimentContract` settable members, 2 errors) | low |
| G7 | Dependency / security hygiene | #1074 §5 | `npm run audit:dependencies` **already wired (blocking) at `frontend-static-pwa.yml:67-69`** (from #1087); `npm audit` = 0 vulnerabilities; 4 transitive lockfile bumps merged 2026-09-20 (`gitpython`, `anyio`, `cryptography`, `soupsieve`); **183 open pip Dependabot alerts (23 critical, 95 high), dominated by `pyqlib 0.9.7` transitive pins** (see §9); old direct pins remain (`numpy<2`, `protobuf<4`, `sqlalchemy<2`, `setuptools==69.5.1`, `pyqlib 0.9.7`) | eliminate the `pyqlib`-rooted alert set via deliberate transitive overrides with qlib compatibility evidence; upgrade the qlib-pinned direct dependencies | no known vulnerable maintained dependency; CI dependency audit remains blocking and green | qlib compatibility testing (mlflow/jupyter stack) | medium |
| G8 | Weekly full-suite safety net | #1074 §5, #1118 | auto-close on recovery landed; PR CI still runs a curated subset | decide the full-suite cadence for `main` | a full-suite regression is caught within one integration cycle | cost/cadence decision | low |

Nothing in G1–G4 can be closed by unit tests alone; each requires a persisted,
operator-visible artifact produced by a governed run.

## 5. Backlog detail — 84 unreferenced modules (2026-09-20 advisory)

The 2026-09-19 advisory reported 85; the 2026-09-20 re-run reports **84 of 527**
because `src/research/factor_identity.py` gained a live caller in
`src/release/quality.py`. The family enumeration below is the 2026-09-19
snapshot and is retained for continuity; treat the advisory count as current.

Derived mechanically by `scripts/check_ci_governance.py` (`dead_modules`
advisory, tracked files only; docs and sealed evidence never confer life).
Grouping is advisory and is not a deletion approval.

### BYD family (21)
`src/research/byd_asymmetric.py`, `src/research/byd_tactical_etf.py`,
`scripts/byd_v12_deep_dive.py`, `scripts/byd_v12_improvement_explorer.py`,
`scripts/byd_v2_regime_research.py`, `scripts/byd_v2_regime_round2.py`,
`scripts/run_byd_515180_trend_guard.py`, `scripts/run_byd_convex_momentum_evidence.py`,
`scripts/run_byd_core_tactical_v1.py`, `scripts/run_byd_defensive_sleeve_screen.py`,
`scripts/run_byd_improvement_experiments.py`, `scripts/run_byd_mom_scaled.py`,
`scripts/run_byd_sma_atr_claim.py`, `scripts/run_byd_trend_fix.py`,
`scripts/run_byd_v1_2_extreme_defense.py`, `scripts/run_byd_v1_2_formal.py`,
`scripts/run_byd_v1_2_promotion_challenge.py`, `scripts/run_byd_v1_2_recovery_state.py`,
`scripts/run_byd_v1_2_trend_expansion.py`, `scripts/run_byd_v1_2_trend_expansion_prospective.py`,
`scripts/run_byd_v1_3_recovery_overlay.py`

### CN27 family (13)
`scripts/formalize_cn_27_v1_3.py`, `scripts/run_cn27_sharpe_discovery.py`,
`scripts/run_cn27_sharpe_holdout.py`, `scripts/run_cn_27_v1_0.py`,
`scripts/run_cn_27_v1_1.py`, `scripts/run_cn_27_v1_2.py`,
`scripts/run_cn_27_v1_2_discovery.py`, `scripts/run_cn_27_v1_3_discovery.py`,
`scripts/run_cn_27_v1_3_projected_discovery.py`, `scripts/run_cn_27_v1_3_prospective.py`,
`scripts/run_cn_27_v1_3_stability_discovery.py`, `scripts/run_cn_27_v1_3_staggered_discovery.py`,
`scripts/run_cn_27_v1_4_discovery.py`

### QQQ / v4.x family (11)
`scripts/bind_v4_2_ledger_source.py`, `scripts/finalize_qqqi_v4_2_rsi_vix_sgov_evidence.py`,
`scripts/promote_qqqi_v4_2_notebook_roles.py`, `scripts/run_qqqi_qqq_tqqq_rotation.py`,
`scripts/run_qqqi_qqq_tqqq_vix_v2.py`, `scripts/run_qqqi_qqq_tqqq_vix_v3_aggressive.py`,
`scripts/run_qqqi_v4_23_xgb_lambdarank_state_machine.py`,
`scripts/run_qqqi_v4_2_donor_state2_sgov_tqqq.py`,
`src/research/v4_15_transition_event_policy.py`,
`src/research/v4_24_xgb_adjacent_path_state_machine.py`,
`scripts/validate_qqqi_v4_24_probability_geometry.py`

### CN ranker / CN data (4)
`scripts/aggregate_cn130_ranking_batches.py`,
`scripts/data/build_cn130_pit_event_families_phase3.py`,
`scripts/data/build_cn_etf_candidate_bundle.py`,
`scripts/run_cn130_tail_factor_discovery.py`

### US ranker / US data (3)
`scripts/create_us_x1_1_sector_cap_shadow_receipt.py`,
`scripts/run_us_x1_1_beta_residual_target.py`,
`scripts/run_us_x1_1_drawdown_attribution_phase_a_canonical.py`

### Data plane / governance / ops tooling (8)
`scripts/archive_snapshots.py`, `scripts/audit_selected_pool_price_sources.py`,
`scripts/data/build_us_raw_adjustment_snapshot.py`,
`scripts/check_multi_market_data_readiness.py`,
`scripts/data/compare_selected_pool_snapshots.py`,
`scripts/data/fetch_cn_current_provider_shard.py`, `scripts/rebuild_watchlist_data.py`,
`scripts/run_factor_feature_quality.py`

### Other (25)
`src/research/all_weather_alpha_rotation_replay.py`, `scripts/benchmark_execution_engine.py`,
`scripts/certify_cn_x1_1_regime_gated.py`, `scripts/cleanup_stuck_jobs.py`,
`scripts/archive/debug_jobs.py`, `scripts/archive/debug_runs.py`, `scripts/disk_quota_manager.py`,
`src/research/excess_returns_training.py`, `scripts/expand_name_map.py`,
`scripts/export_model_run_bundle.py`, `src/research/factor_identity.py`,
`scripts/utils/filter_us_universe.py`, `scripts/generate_arena_report.py`,
`src/research/notebook_training_api.py`, `scripts/promote_cn_formal_freshness.py`,
`scripts/utils/register_all_runs.py`, `scripts/register_existing_reports.py`,
`scripts/repair_run_artifacts.py`, `scripts/run_all_weather_alpha_rotation.py`,
`scripts/run_factor_redundancy.py`, `scripts/run_real_market_research.py`,
`scripts/run_risk_control_variants.py`, `scripts/run_spec_bound_factor_diagnostics.py`,
`scripts/run_top_bottom_analysis.py`, `scripts/train_cn_best_v2.py`

Disposition rule per #1074: once a canonical path exists, the superseded path is
**deleted**, not wrapped. Until then it stays, because research reproduction
capability is itself governed memory.

## 6. Execution order

1. **G1** — regenerate the 2026-09-11 US x1.3 current target on the corrected
   provider and re-seal the ledger (unblocks the operating loop).
2. **G2, G3** — PIT fundamentals and the US87 Alpha158 panel (unblock G4).
3. **G4** — canonical training plane vertical slice (US x1.2).
4. **G5** — per-family archival/deletion of the 84-module backlog; workflow
   convergence.
5. **G6, G7, G8** — static-check ratchet, dependency hygiene, full-suite cadence.

## 7. Guardrails

- All outputs remain `research_only=true`, `trade_ready=false`.
- No silent drop, forward-fill, substitution or raw/adjusted mixing.
- A blocked or partial upstream component fails closed; it is never patched
  with validation-only providers or synthetic fields.
- Deletions preserve git history; no committed evidence is rewritten.

## 8. Session log — 2026-09-20 sync and triage

Actions taken this session (all `research_only=true`, `trade_ready=false`):

1. **Repository sync** — `main` fast-forwarded to `origin/main`; working tree
   clean; no divergence.
2. **Dependency PRs merged** — `#1121` gitpython `3.1.46→3.1.59`, `#1122` anyio
   `4.12.1→4.14.2`, `#1123` cryptography `46.0.5→50.0.0`, `#1124` soupsieve
   `2.8.3→2.9`. All four were lockfile-only transitive bumps with green CI;
   `uv lock --check` exits 0 on the merged tree. This advances **G7**.
3. **Strict-mypy ratchet (G6)** — five canonical modules made type-clean and
   added to the strict scope in `pyproject.toml` and `.github/workflows/ci.yml`:
   `src.research.ranker_current_target`, `src.research.drift_monitor`,
   `src.research.stage_journal`, `src.governance.research_mandate`,
   `src.artifacts.strategy_operations`. Commit `chore(typing): ratchet five more
   canonical modules into strict mypy`. Verification: `mypy` 28 source files
   pass; `ruff` clean; 68 targeted tests pass; `check_ci_governance --enforce`
   0 violations.
4. **Security-update PRs** — after the first merges, Dependabot opened four
   security updates; three were merged: `#1126` sqlparse `0.5.5→0.6.0`, `#1127`
   tornado `6.5.4→6.5.8`, `#1129` pyjwt `2.11.0→2.13.0` (all lockfile-only,
   green CI). `#1128` mlflow `1.27.0→3.16.0` was **deliberately held** (see §9)
   with an explanatory comment on the PR. Post-merge verification: `uv lock
   --check` exits 0; `import mlflow/tornado/jwt/sqlparse` resolve to the locked
   versions (mlflow stays 1.27.0); `from qlib.workflow import R` imports;
   `tests/test_architecture_contract.py` 6 passed.

Corrected/stale facts in this report:

- G7's "`npm run audit:dependencies` wired into CI" was **already satisfied**
  by #1087 (`frontend-static-pwa.yml:67-69`, blocking step); `npm audit` is
  currently 0 vulnerabilities. The remaining G7 work is the qlib-pinned direct
  dependencies, not the audit wiring.
- `dead_modules` advisory is now **84 of 527** (was 85); `factor_identity`
  converged.

Remaining and explicitly deferred (unchanged authority):

- **G1** — blocked at the operational layer: the committed `2026-09-11` US x1.3
  current target still contains terminal listing `EA`, so the formal refresh
  correctly fails closed. Unblocking requires a **governed regeneration** of
  that current target on the corrected provider and re-sealing the ledger. This
  is a data/evidence publication action and was **not** performed in this
  session; it needs the provider environment and owner-governed execution.
- **G2** — close per-symbol PIT gaps: `301666` (CN, provider_missing) and
  `SBGSY` (US, identity_missing).
- **G3** — materialize the US87 Alpha158 panel (shares the `301666` blocker).
- **G4** — canonical training plane; gated on G2/G3.
- **G5** — per-family archival/deletion of the 84-module backlog; each family
  still requires owner approval before deletion.
- **G6 (next unit)** — `cn_x1_2_current_target` protocol debt: 2 remaining
  strict-mypy errors from `CrossSectionalExperimentSpec` vs
  `RankerExperimentContract` (settable protocol members).
- **G8** — full-suite cadence for `main` remains an owner decision; weekly cron
  and auto-close are in place, PR CI still runs a curated subset.

No committed evidence, registry, or model artifact was modified by this session.

## 9. G7 dependency-risk evidence — 2026-09-20

GitHub reports **183 open Dependabot alerts** on `main` (23 critical, 95 high,
54 medium, 11 low), all `pip`/`uv.lock`. `npm audit` reports 0, so this set is
Python-only. Root cause: `pyqlib 0.9.7` transitively pins an obsolete stack.

| Package | Alerts | Worst severity | Root | Patched version exists |
| --- | --- | --- | --- | --- |
| mlflow (1.27.0) | 73 | critical (22) | `pyqlib` → `mlflow` | yes (2.x/3.x) |
| mistune | 16 | high | `pyqlib` → `nbconvert` | yes (3.2.1+) |
| pillow / Pillow | 18 | high | `pyqlib` → `matplotlib`/notebooks | yes (12.3.0) |
| tornado | 9 | high | `pyqlib` → `jupyter` | yes (6.5.5+) |
| jupyterlab / jupyter-server | 14 | critical | `pyqlib` → `jupyter` | yes (4.5.x / 2.18+) |
| setuptools (`==69.5.1`) | 6 | high | direct pin | yes (78.1.1+) |
| python-multipart, sqlparse, pyjwt, starlette, protobuf, bleach, urllib3, Mako, pydantic-settings, lxml, idna, python-dotenv, mcp | remainder | high/medium | mixed (`mcp`, direct pins, transitive) | mostly yes |

Counts above are the pre-merge snapshot. The `sqlparse`, `tornado` and `pyjwt`
security bumps were merged (see §8.4); GitHub's dependent rescans had not yet
refreshed the alert list at record time, so those packages may still appear
until the next scan.

Verified non-destructively this session: `uv lock --upgrade-package mlflow`
resolves `mlflow 3.16.1` under `pyqlib 0.9.7` (no hard `==1.27.0` pin), the
lock passes `uv lock --check`, and `import mlflow` succeeds. That single change
would remove **73 of 183 alerts including 22 critical**. It was **reverted and
its Dependabot PR `#1128` held** because it is a ~1085-line lock change that
changes qlib's MLflow recorder surface and therefore requires dedicated qlib
compatibility testing and owner sign-off, per this workstream's "deliberate
upgrades" rule. This is not hypothetical: the project uses qlib's MLflow-backed
recorder in `src/common/qlib_init.py` (`qlib.workflow.expm`, sqlite MLflow
backend), `src/research/backtest.py` (`from qlib.workflow import R`) and
`src/api/mcp_server.py`, against an API surface `pyqlib 0.9.7` was built for at
mlflow 1.x. No project module imports `mlflow` directly.

Recommended next unit: land the `mlflow` override in an isolated PR with a qlib
recorder smoke test, then proceed package-by-package (`mistune`, `pillow`,
`tornado`, `jupyter*`) with the same evidence standard, and separately revisit
the `setuptools==69.5.1` direct pin.
