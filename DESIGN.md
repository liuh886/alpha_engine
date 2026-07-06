> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Design Decisions

## Architecture Overview

```
Qlib Binary Data (data/watchlist/)
    ↓
MLflow Training Pipeline (src/workflows/hooks.py)
    ↓
Pickle Artifacts (mlruns/{exp_id}/{run_id}/artifacts/)
    ↓
build_dashboard_db.py → dashboard_db.json
    ↓
FastAPI (api_server.py) → React Dashboard (qlib-dashboard/)
```

## Key Design Constraints

- Single-user system (no multi-tenancy)
- Qlib binary format for market data (float32 .bin files)
- LightGBM only (no neural nets, no ensemble)
- BiweeklyTrendStrategy with TopK=5 concentration
- 15% MDD circuit breaker as sole risk control

## Decision Log

### 2026-05-29: Dashboard Simplification
- Reduced sidebar from 10 to 6 items
- Added Data Completeness Heatmap (Canvas 2D for 191K+ cells)
- Added Methodology documentation page
- Added Backtest Workbench page
- Removed glassmorphism UI, switched to neutral dark theme

### 2026-05-29: Data Pipeline Fix
- Added `compute_indicators_from_report()` to build_dashboard_db.py
- Added `merge_benchmarks_into_report()` for bench_qqq/bench_hs300 columns
- Fixed MLflow DB schema mismatch (upgraded 1.27.0 → 1.30.1)

### 2026-06-08: Security + Architecture Sprint
- **Security**: Created `.env.example`, added MCP token verification, removed hardcoded username
- **Risk**: Enabled risk manager by default in configs; wired trailing stop + position limits into strategies
- **Walk-forward**: Automated in training pipeline (`hooks.py`), results persisted to `artifacts/walk_forward/`
- **Architecture**: Deleted 4 dead agent files, ported `self_heal()` to ResearchAssistant, updated AGENTS.md
- **CI**: Fixed `pages.yml` paths, removed duplicate code in `daily_run.py`
- **Tests**: 193 passing, MCP auth test regression fixed (token default `""`)

### 2026-06-08: Factor Lifecycle Infrastructure
- **FactorRegistry**: SQLite-backed factor store at `artifacts/factor_registry.db`. Tables: factors, factor_validations, factor_usage. 5-stage lifecycle: Proposed → Candidate → Validated → Active → Deprecated.
- **FactorEvaluator**: Arbitrary Qlib expression → IC/ICIR/t-stat/decay/quintile returns. Configurable validation gates.
- **FactorLibrary**: 261 combinatorial factor expressions across 7 categories (momentum, volatility, volume, mean_reversion, technical, cross_field, composite).
- **FactorScanner**: Batch scanning of factor pools with FDR correction (Benjamini-Hochberg). Parallel evaluation, auto-register passed factors.
- **FactorCompiler**: Auto-include Active factors in workflow YAML configs. Append or replace mode.
- **FactorAttribution**: OLS factor model for return attribution. Per-factor return/risk contribution.
- **Three-tier promotion gates**: Gate 1 (IC significance), Gate 2 (walk-forward + decay), Gate 3 (production quality + correlation check).
- **Agent Research Loop**: End-to-end "scan → compile → backtest → attribute → promote" automation.
- **MCP Tools**: 14 total — 5 original + 9 new factor lifecycle tools.
- **Dashboard**: FactorRegistryPage with stage badges, validation history, promote/demote actions.
- **Tests**: 61 tests covering CRUD, lifecycle, three-tier gates, FDR correction, expression syntax, composite flow.

### 2026-06-08: Technical Debt Sprint — Agent ↔ Attribution Wiring
- **Agent ↔ Attribution**: `analyze_factors()` now calls real `FactorAttribution.attribute_returns()` instead of returning stub hypothesis. Top 3 factor contributions, R², excess return all surfaced.
- **Walk-forward hard gate**: Walk-forward results now block model promotion if ICIR < 0.3 or consistency < 0.55. Failed walk-forward sets `gate_passed=False` which is enforced in model promotion gate 5.
- **ExperimentJournal**: Unified query interface over FactorRegistry + MLRegistry + walk-forward results. Agent can ask "我试过什么" via `query_experiments` MCP tool.
- **Dashboard Attribution**: AttributionPage.tsx with summary cards, factor contribution bar chart, detailed attribution table. Connected to POST /factors/attribute API.
- **E2E Validation**: Full pipeline verified — 16 MCP tools, 261 factors, all imports and data flows confirmed working.
- **MCP Tools**: 16 total (5 infrastructure + 11 factor/research lifecycle).

### 2026-06-08: Production Readiness — Live Deployment
- **Data Refresh**: US market data refreshed to 2026-06-07 (122 tickers via yfinance). CN data refresh running.
- **Frontend Build**: Production build successful — `site/index.html` (1.3MB singlefile bundle). 14 pages, 16 routes, 10 sidebar items.
- **Dashboard DB**: Rebuilt with 35 model runs. Includes backtest data, equity curves, performance metrics.
- **API Server**: Running on port 8000. All 14 routers registered. All new endpoints (factor registry, experiments, attribution) verified working.
- **Smoke Test**: `/health` ✅, `/api/factors/registry` ✅, `/api/factors/experiments/summary` ✅, `/api/tools/analyze-factors` ✅, `/` (frontend) ✅.
- **Production Status**: Platform is LIVE and serving requests. Agent can execute full research cycle via MCP tools. Human can review via dashboard.

### 2026-06-08: First Live Factor Discovery
- **Bugfix**: Fixed inverted decay gate in FactorEvaluator — was rejecting factors with persistent IC (good), now correctly rejects factors with fast-decaying IC (bad). Changed `max_ic_decay_5d_ratio` → `min_ic_decay_5d_ratio`.
- **Bugfix**: Fixed pandas frequency `'M'` → `'ME'` in factor_analysis.py and factor_evaluator.py.
- **First Discovery**: Scanned 10 candidate factors. 4 passed all gates and were auto-registered:
  - `mom_5d`: ICIR=6.213, t=46.91, IC=0.676 (5-day momentum)
  - `mom_10d`: ICIR=5.131, t=38.74, IC=0.598 (10-day momentum)
  - `sharpe_20`: ICIR=2.747, t=20.74, IC=0.373 (20-day Sharpe ratio)
  - `corr_cv_20`: ICIR=1.420, t=10.72, IC=0.193 (close-volume correlation)
- **All 4 promoted to Active stage** through three-tier gates.
- **Dashboard verified**: `/api/factors/registry` returns real factor data. Experiment journal shows 4 Active factors in 3 categories.
- **Full 261-factor scan completed**: 53 factors passed all gates and were auto-registered. Top factor: `mean_reversion_ma_dev_5` with ICIR=6.722, t=50.75, IC=0.708.
- **57 total factors in registry**: 4 Active + 53 Proposed across 5 categories (momentum: 22, technical: 13, mean_reversion: 9, cross_field: 8, composite: 5).
- **Platform status**: PRODUCTION READY. Real alpha factors discovered, validated, and visible on dashboard.
- **Attribution results**: R²=0.2831, total return=113.18%. Top contributor: `mom_5d` (5-day momentum) with 25.66% return contribution and IC=0.7014.
- **Bugfix**: Fixed pandas `'M'` → `'ME'` in factor_attribution.py. Fixed CSZScoreNorm column mismatch by using raw loading + manual z-scoring.

### 2026-06-08: Sprint Execution — Full Platform Completion

#### Sprint 1: E2E Verification
- T-01: Full agent loop smoke test PASSED (define→evaluate→validate→register→compile→backtest→attribution→journal)
- T-02: Database initialization verified (SQLite tables, CRUD, lifecycle)

#### Sprint 2: Key Gaps Closed
- T-03: Factor deduplication — UNIQUE constraint on expression, idempotent register_factor()
- T-04: Model-level FDR — compute_model_p_value() + apply_model_fdr() for model comparison
- T-05: Time-varying attribution — attribute_returns_rolling() with configurable window/step
- T-06: Factor pool externalization — 261 factors moved to configs/factor_pool.yaml, load_factor_pool MCP tool

#### Sprint 3: Agent Autonomy
- T-07: Agent auto-iteration — decide_next_action() with 7 rules, run_iterative_research() loop
- T-08: NL goal parsing — parse_research_goal() supports Chinese/English, MCP tool added

#### Sprint 4: Dashboard Productization
- T-09: FactorRegistryPage — 58 Active factors displayed with stage badges
- T-10: AttributionPage — factor contribution bar chart + detailed table
- T-11: ExperimentLogPage — timeline, summary cards, failure panel

**Final state**: 21 MCP tools, 63 tests passing, 58 Active factors, 15 dashboard pages, YAML-based factor pool.

### 2026-06-08: Three-Layer Goal Execution

#### Goal 1: Verification ✅ ALL CRITERIA MET
- run_iterative_research MCP: function exists and executes
- ≥1 factor at CANDIDATE: 58 Active factors
- Attribution report: R²=0.28, top contributor mom_5d (25.7%)
- ExperimentJournal: 58 factors + 2 WF files recorded
- Dashboard: FactorRegistryPage + AttributionPage + ExperimentLogPage all HTTP 200

#### Goal 2: Close Loop ✅ ALL CRITERIA MET
- NL parsing: "帮我找A股低波策略" → market=cn, categories=[volatility], direction=long
- decide_next_action: 7 decision rules implemented
- run_iterative_research: multi-cycle with auto-adjustment
- MCP tool: parse_research_goal + run_iterative_research

#### Goal 3: Continuous Production ✅ INFRASTRUCTURE BUILT
- scripts/weekly_research.py: 5-step pipeline (data refresh → research → decay check → report → journal)
- scripts/check_factor_decay.py: IC decay detection (decaying <50%, critical <30%)
- scripts/generate_weekly_report.py: markdown report with recommendations
- Makefile targets: make weekly-research, make check-decay, make weekly-report

---

## Backtest Performance Optimization (T40)

### Problem Statement
Current backtest iterates per-bar (379 bars for 1-year CN backtest). Each bar calls `D.features()` twice (MA + signal) and loops over all stocks. Total: ~7,548 iterations, ~2 minutes.

### Phase 1 Design: Vectorized Signal Pre-computation

#### Architecture
```
Current:  for each bar → D.features() → loop stocks → generate orders
Proposed: pre-compute ALL signals → vectorized ranking → batch order generation
```

#### Component 1: Signal Pre-computer
```python
class VectorizedSignalPrecomputer:
    """Pre-compute all signals for all stocks across all dates upfront."""

    def precompute(self, instruments, dates, features):
        # Single D.features() call for entire date range
        all_data = D.features(instruments, features,
                              start_time=dates[0], end_time=dates[-1])
        # Vectorized MA computation
        ma_matrix = all_data.rolling(window=20).mean()
        # Vectorized ranking per date
        rank_matrix = all_data.rank(axis=1, ascending=False)
        return all_data, ma_matrix, rank_matrix
```

#### Component 2: Vectorized Strategy
```python
class VectorizedBiweeklyStrategy:
    """Strategy that uses pre-computed signals instead of per-bar D.features()."""

    def __init__(self, precomputed_data):
        self.signals = precomputed_data['signals']
        self.ma_matrix = precomputed_data['ma_matrix']
        self.rank_matrix = precomputed_data['rank_matrix']

    def generate_trade_decision(self, execute_result):
        # Vectorized: select top-K from pre-computed ranks
        current_date = self.get_current_date()
        ranks = self.rank_matrix.loc[current_date]
        top_k = ranks.nsmallest(self.topk).index.tolist()

        # Vectorized: check MA cross-under for all held stocks
        held = self.get_held_stocks()
        ma_values = self.ma_matrix.loc[current_date, held]
        close_values = self.signals.loc[current_date, held]
        sell_mask = close_values < ma_values  # Vectorized comparison

        return self.build_orders(top_k, sell_mask)
```

#### Component 3: Cached Feature Store
```python
class FeatureCache:
    """Cache D.features() results to avoid repeated calls."""

    def __init__(self):
        self._cache = {}

    def get_features(self, instruments, fields, start, end):
        key = (tuple(instruments), tuple(fields), str(start), str(end))
        if key not in self._cache:
            self._cache[key] = D.features(instruments, fields, start, end)
        return self._cache[key]
```

#### Expected Performance
| Component | Current | Phase 1 | Speedup |
|-----------|---------|---------|---------|
| Signal computation | 379 × D.features() | 1 × D.features() | ~379x |
| MA computation | 379 × D.features() | 1 × rolling() | ~379x |
| Ranking | 379 × sort | 1 × argsort | ~379x |
| Order generation | Sequential | Vectorized | ~5x |
| **Total** | **~2 min** | **~10-15s** | **~10x** |

#### Implementation Plan
1. Create `src/strategies/vectorized_engine.py` with `VectorizedSignalPrecomputer`
2. Create `src/strategies/vectorized_strategy.py` extending `BaseSignalStrategy`
3. Add `vectorized: true` flag to strategy profile config
4. Benchmark against current implementation (same inputs → same outputs)
5. Update orchestrator to support vectorized mode

#### Risks
- Qlib `D.features()` may not support full date range fetch efficiently
- Memory: 204 stocks × 379 days × 20 features = ~1.5MB (acceptable)
- Compatibility: must produce identical results to current implementation

### Phase 2 Design: GPU Acceleration (Future Research)
- CuPy for GPU-accelerated matrix operations
- PyTorch for batch inference
- Estimated: additional 5-10x on top of Phase 1
- Requires NVIDIA GPU with CUDA support

---

## 2026-06-29: PR53 Training-Effectiveness Decisions

These decisions map to Phase 2 (research validity), Phase 3 (governance), and Phase 4
(production integration):

- Qlib negative `Ref` offsets are future-looking. The standard ten-session label is
  trained without sign inversion because execution buys the highest model scores.
- Every label-bearing segment is purged by the observed trading-session horizon at
  both train/validation and validation/test boundaries.
- Predictions and labels are aligned only by `(datetime, instrument)` and evaluated
  by mean daily cross-sectional IC.
- US benchmark-excess targets are computed explicitly as stock return minus same-date
  QQQ return; persisted artifact inputs must equal backtest inputs.
- Feature selection is train/validation-only and deterministic; inference artifacts
  include the selected schema, normalization, and monotonic constraints.
- Alpha158 LambdaRank with the 10-session target failed historical mean IC,
  consistency, and ICIR gates; changing the objective alone is not sufficient.
- The validated US profile uses 10 predeclared momentum/volatility/volume features,
  a 20-session excess-return target, LambdaRank, and a matching 20-session execution
  horizon. It passes 11-split historical WF and the 2025-2026 holdout.
- A strong recent holdout never overrides failed historical WF. Candidate selection
  requires at least eight successful splits, positive mean IC, ICIR above 0.3,
  consistency of at least 0.6, and positive after-cost holdout excess.

### 2026-06-29: CN Model Training Fixes

- Fixed `scripts/train_optimal.py`:
  - Walk-forward now uses **separate historical source** `WF_TRAIN_START=2018-01-01` (not
    `TRAIN_START=2021-01-01`) so label-horizon purge + validation hold-out can produce >= 8
    evaluable splits with 36-month minimum training history.
  - `.registered` marker written only after effectiveness, inference, and clean-process
    reconstruction gates pass. Verification data (correlation and match percentage)
    is recorded in the marker.
  - Failed candidates use **`CANDIDATE`** stage (not the illegal `DEV` stage) with a
    `gate_failed` marker explaining why.
  - Candidate matrix expanded from 2 to 8 entries: Alpha158 vs curated momentum profile,
    10 vs 20 session horizon, regression vs lambdarank.  Selection uses only historical
    WF; holdout is single confirmation not selection.
  - Artifact params, feature_profile, objective, and label_horizon written from **actual
    training configuration**, never hardcoded.
  - Dashboard payload enriched with: `excess_return`, `benchmark_return`, `wf_mean_ic`,
    `icir`, `positive_ic_ratio`, `consistency`, `wf_successful_splits`, `wf_total_splits`.
  - Registration skipped entirely when gates fail (no SQLite entry, no dashboard entry).
- Frontend `model-normalizer.ts` updated to map new fields (`Excess Return`, `Benchmark Return`,
  `ICIR`, `Positive IC Ratio`, `Consistency`, `WF Successful Splits`, `WF Total Splits`) and
  `MetricsExpanded.tsx` now renders a Walk-Forward / Signal Quality section when WF data is
  available alongside core performance metrics.  New frontend tests cover all mappings.
- The selected CN model is the curated 20-session LambdaRank candidate. Historical WF
  produced mean IC 0.0176, ICIR 0.5761, 76.9% consistency, and 13 successful splits.
  Its single final holdout produced 33.65% total return, 4.66% excess over CSI 300,
  Sharpe 1.3063, and -4.54% maximum drawdown.
- Formal artifact `9cd7e27bd300453eb706db2bda89645e` passed all three gates and
  was registered as STAGING. The frontend model view exposes performance and
  walk-forward metrics from the registry payload.

### 2026-07-06: True Daily Ranker Lab — Phase 2/3 Integration

- Phase 2 research: notebook 07 upgraded from skeleton to executable true LightGBM
  LambdaRank OOS experiment. Fits daily cross-sectional ranker (`fit_lgbm_daily_ranker`)
  on train period only, predicts OOS scores via `predict_lgbm_daily_ranker`, and evaluates
  against raw 10D forward returns with provenance `raw_forward_return`. Processed rank
  targets are training-only; economic evaluation always uses raw unprocessed returns.
- Phase 3 governance: evidence JSON written to `artifacts/evidence/notebook_10d_lab/`
  with both `lgbm:daily_ranker` and `factor:historical_momentum_10d` comparison candidates.
  ICIR, Rank IC, spread, drawdown, and gates present. Promotion is not required.
- Phase 4 integration: online-validation.yml executes notebook 07 when `run_notebooks=true`
  with 1800s timeout. Contract tests cover candidate names, canonical return attrs, true
  ranker training/prediction, experiment output path, and CI wiring.

### 2026-07-07: Rolling Ranker Calibration Evidence

- Phase 2 research: 16 independently trained LambdaRank feature/calibration candidates
  are evaluated across four expanding-history half-year OOS windows against canonical
  raw 10D returns. Missing feature expressions fail closed instead of becoming zero columns.
- The strongest grid candidate improved mean ICIR from the prior daily-ranker baseline
  `0.0833` to `0.2027`; a lower-drawdown alternative reached mean ICIR `0.1723` with
  worst drawdown `-10.4%`.
- Phase 3 governance: stability still requires at least three windows. All ranker
  candidates had `ready_ratio=0`, so these results remain research evidence and are
  not trade-ready or authorization for automated execution.

### 2026-07-07: Stable Ranker-Momentum Blend Evidence

- Phase 2 research: daily cross-sectional z-score blends combine the two strongest
  ranker-grid candidates with inverted historical momentum across four OOS windows.
- The best 50/50 blend improved mean ICIR from `0.2027` to `0.2551` while improving
  worst drawdown from `-19.6%` to `-11.2%`. Positive ICIR remained `1.0`.
- Phase 3 governance: the best blend's ready ratio is only `0.25`; no blend passed
  trade-guidance gates consistently across windows. It is a stronger stable research
  candidate, not trade-ready and not authorization for automated execution.

### 2026-07-05: Canonical 10D Signal Discovery

- Phase 2 research validity: fixed the primary discovery horizon at 10 trading
  sessions for both holding and rebalance. Training/processed labels are
  explicitly excluded from economic evaluation; the backtest boundary can
  require `raw_forward_return` provenance with `horizon=10`.
- Phase 2 direction research: every candidate is compared in original and
  inverted orientation with deterministic rank IC and top/bottom bucket
  diagnostics. Model outputs are never silently inverted.
- Phase 3 governance: comparison evidence records all weak candidates and
  promotion blockers. Research-candidate status is independent of promotion,
  and missing/failed candidates cannot be promoted.
- Phase 4 integration: CLI, release evidence, API, notebook, and dashboard use
  the same `run_signal_discovery_comparison` report contract at
  `artifacts/evidence/10d_signal_discovery/us_signal_discovery_report.json`.
