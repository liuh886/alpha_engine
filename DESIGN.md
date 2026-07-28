> Capability Router Protocol
> This file is a long-lived project state file.
> Do not rewrite this file wholesale.
> Only append new entries or edit explicitly conflicting fields after user confirmation.
> If a request conflicts with existing content, surface the conflict first.

# Design Decisions

## Current Status (2026-07-18)

Alpha Engine is a **research-only platform**. Key points:

- **Paradigm**: Fixed 10D horizon, spec-bound execution (`configs/research_paradigms/`)
- **Runtime**: `SpecBoundResearchWorkflowExecutor` is the sole runtime (ADR-0006/0007)
- **Promotion**: `PromotionDecision` is the single promotion interface (ADR-0005), fail-closed on missing evidence
- **Agents**: Unified `ResearchAssistant` — the four-agent architecture (Alpha, Risk, Governance, Developer) is superseded
- **Trading**: **No model is trade-ready.** All outputs are diagnostic-only or research candidates
- **Evidence**: Latest 2026-07-16 run at `docs/evidence/issue-124-current-2026-07-16/` — both CN/US `diagnostic_only=true`
- **Deployment**: Not deployed for live trading. Demo mode (`--demo`) for UI exploration only

Historical claims in this document (e.g., "LIVE", "PRODUCTION READY") are preserved below
as records of prior development milestones but are superseded by the current research-only scope.

---

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
- **Production Status** (historical — superseded by research-only scope): Platform was LIVE and serving requests in a prior development milestone. Current scope is research-only; no model is trade-ready. Agent can execute full research cycle via MCP tools. Human can review via dashboard.

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
- **Platform status** (historical claim — superseded by research-only scope): PRODUCTION READY was declared during prior factor-discovery milestones. Current status: research-only, diagnostic-only evidence, no model trade-ready.
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
- T-07 (historical — superseded by ADR-0009): Agent auto-iteration — decide_next_action() with 7 rules, run_iterative_research() loop. Both functions are retired; the canonical spec-bound workflow uses a single `run_research_cycle` call.
- T-08: NL goal parsing — parse_research_goal() supports Chinese/English, MCP tool added

#### Sprint 4: Dashboard Productization
- T-09: FactorRegistryPage — 58 Active factors displayed with stage badges
- T-10: AttributionPage — factor contribution bar chart + detailed table
- T-11: ExperimentLogPage — timeline, summary cards, failure panel

**Final state**: 21 MCP tools, 63 tests passing, 58 Active factors, 15 dashboard pages, YAML-based factor pool.

### 2026-06-08: Three-Layer Goal Execution

#### Goal 1: Verification ✅ ALL CRITERIA MET
- run_iterative_research MCP (historical — superseded by ADR-0009): tool was removed; callers use `run_research_cycle` for a single canonical execution
- ≥1 factor at CANDIDATE: 58 Active factors
- Attribution report: R²=0.28, top contributor mom_5d (25.7%)
- ExperimentJournal: 58 factors + 2 WF files recorded
- Dashboard: FactorRegistryPage + AttributionPage + ExperimentLogPage all HTTP 200

#### Goal 2: Close Loop ✅ ALL CRITERIA MET
- NL parsing: "帮我找A股低波策略" → market=cn, categories=[volatility], direction=long
- decide_next_action (historical — superseded by ADR-0009): retired with research_loop.py; the canonical path has no adaptive iteration
- run_iterative_research (historical — superseded by ADR-0009): retired; the canonical spec-bound workflow does not loop
- MCP tool: parse_research_goal + run_research_cycle (run_iterative_research was removed per ADR-0009)

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

### 2026-07-26: Nasdaq-100 Window-Start Universe Validation

- Phase 2 research validity: frozen candidate_v2 was retrained and evaluated
  over four half-year OOS windows using official Nasdaq-100 membership frozen
  at each window start and the latest semiannual as-of membership for every
  training row. The future OOS snapshot is never applied backwards to training.
  The static-100 result did not replicate: compounded relative excess was
  `-19.90%`, only one of four windows was positive, mean ICIR was `0.1899`,
  and worst drawdown was `-21.01%`.
- Phase 3 governance: provider coverage was incomplete at every snapshot
  (from 68/102 in 2021 to 93/101 in 2025). The evidence uses semiannual as-of
  training membership and window-start OOS membership, not full daily PIT.
- The frozen gate failed on positive-excess windows, compounded relative
  excess, and drawdown. `promotion_eligible=false` and `trade_ready=false`.
- As-of membership improves relative excess, ICIR, and drawdown versus applying
  the future OOS snapshot across training, but the next validity step is
  provider backfill, not more blend-weight, LightGBM, or overlay tuning.

### 2026-07-26: Near-Complete NDX Provider Backfill and Documentation Cleanup

- Phase 1 data validity: an isolated US provider backfilled 34 historically
  required NDX symbols without mutating the operational provider. OOS coverage
  rose from 86-93 symbols to 98-100 symbols; unavailable acquired or delisted
  names remain explicit, so coverage still fails closed as partial. A
  mixed adjusted/unadjusted `KLAC` history was detected before holdout
  interpretation; the builder now scans seeded close series for split-like
  discontinuities, refreshes the full affected history, records both hashes,
  and fails closed if the anomaly remains. The repaired isolated-provider
  identity is
  `6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407`.
- Phase 2 research validity: the unchanged candidate_v2 deteriorated under the
  broader universe. Repaired authoritative evidence reports `-39.21%`
  compounded relative excess, zero positive-excess windows, mean ICIR `0.1103`,
  and `-29.64%` worst drawdown.
  Training coverage is now checked only over each symbol's actual semiannual
  membership interval, so ticker exits are neither discarded nor rescued by
  future bars. This is evidence of prior coverage optimism, not a promotion.
- Phase 3 governance: `promotion_eligible=false` and `trade_ready=false` remain
  mandatory.
- Phase 4 integration: WebUI's main documentation endpoint now serves the
  maintained root `README.md`. Unreferenced retired-agent plans and duplicate
  architecture documents were removed; current `README.md`, `DESIGN.md`,
  `AGENTS.md`, `evaluation.md`, and `docs/adr/` remain authoritative.

### 2026-07-26: Top-3 Objective Alignment Falsification

- Phase 2 research validity: one predeclared structural variant replaced the
  five-bin daily target with exact binary Top-3 relevance and set LambdaRank
  truncation to six. All other model, blend, portfolio, cost, embargo, and
  benchmark controls stayed frozen.
- Phase 1 data validity: the official 2026-01-02 NDX snapshot retained 101/101
  symbols. Horizon-contained raw 10D returns yielded 109 sessions and 11
  rebalance periods through 2026-06-09.
- Phase 2 result: versus the frozen model, the aligned model improved relative
  excess by 5.31 percentage points and drawdown by 1.28 points, but still lost
  28.76% relative to QQQ, drew down 23.37%, and worsened exact Top-3 spread
  from -4.17% to -5.01%. Only 3/11 Top-3 periods were positive.
- Phase 3 governance: the single-window decision is
  `top3_alignment_not_supported_on_holdout`. It is falsification-only,
  `promotion_eligible=false`, and `trade_ready=false`. Further gain-bin,
  truncation, or Top-K tuning in this model family is not an approved next
  step; a future hypothesis must change the economic information set or label.

### 2026-07-26: Benchmark-Residual Trend-Quality Diagnosis

- Phase 2 research validity: the first post-ranker hypothesis uses one frozen
  transparent signal: 126 historical daily returns, a 10-session skip, rolling
  QQQ beta removal, and residual mean divided by residual volatility. The
  orientation is fixed and no parameter grid, future return, or neutral fill
  is allowed.
- Phase 2 result: versus frozen candidate_v2, complete-window total return
  improves from 3.84% to 19.17%, compounded relative excess from -39.21% to
  -30.23%, worst drawdown from -29.64% to -27.55%, and exact Top-3 spread from
  .093% to 1.202%. The 2026H1 partial stress window produces +17.58% relative
  excess and +7.37% Top-3 spread.
- Phase 2 limitation: only one of four complete windows has positive excess,
  mean ICIR falls to .054, the drawdown floor still fails, and selected beta
  changes from strongly defensive to strongly aggressive across regimes.
  The signal therefore cannot replace the rejected model.
- Phase 3 governance: all evaluated windows were already observed, and the
  partial window cannot compensate for cross-window failure. Decision:
  `residual_trend_quality_not_supported`, `promotion_eligible=false`, and
  `trade_ready=false`. The frozen 126/10 signal may receive one independent
  market or future-window challenge; no same-window blend or parameter search
  is approved.
- Phase 2 independent-market result: the unchanged 126/10 formula was
  challenged on the canonical CN/CSI300 contract with Top-15. Across four
  complete windows it produced 25.10% versus CSI300's 39.13%, -10.08%
  compounded relative excess, 2/4 positive windows, mean ICIR .056, -15.08%
  worst drawdown, and 54% positive Top-15 periods.
- Phase 3 final decision: the CN challenge also fails the excess-window,
  compounded-excess, drawdown, and tail-consistency gates. Static current CN
  membership additionally retains explicit survivorship bias. Decision:
  `cn_residual_trend_quality_not_supported`; the 126/10 hypothesis is stopped
  across both markets without tuning lookback, skip, orientation, or Top-K.

### 2026-07-29: Cross-Market Technical-Indicator Diagnosis

- Phase 1 data validity: the original CN provider contained 46 material OHLC
  relationship defects on 2024-03-29. Yahoo's raw and auto-adjusted payloads
  were both internally inconsistent. An isolated fail-closed rebuild replaced
  only those 46 full histories through EFinance qfq, preserved all 212 source
  identities, achieved minimum 99.13% date overlap, and produced zero invalid
  rows. The repaired provider identity is
  `6f556a5952b220b0a92545046ffc1a738227d3b4fb216303a5b0f08762cd50f4`.
  Calendar and instrument hashes are unchanged, so parent readiness is reused
  only through explicit repair lineage. US historic NDX membership remains
  near-complete; CN static membership retains survivorship bias.
- Phase 2 research validity: fixed Bollinger-reversion, MACD-histogram, and
  RSI-strength factors were evaluated on four complete 2024H1--2025H2 OOS
  windows with raw forward 10D returns. No parameter or orientation search was
  performed. CN RSI is the strongest local clue (mean ICIR .0986, -12.95%
  worst drawdown, +9.99% compounded relative excess), but only 2/4 windows
  beat CSI300 and the factor fails completely in US.
- Phase 2 high/low challenge: one fixed 10-session close-location-pressure
  factor was evaluated after the repair. It produced mean ICIR -.0096 and
  -17.04% relative excess in US, and mean ICIR .0200 with -9.34% relative
  excess in CN. It is falsified without a window or orientation search.
- Phase 3 governance: no candidate passes the cross-market economic gate;
  `supported_candidates=[]`, `promotion_eligible=false`, and
  `trade_ready=false`. The active factor libraries are unchanged. A precedence
  defect in the inactive RSI factor-pool formulas was corrected and locked by
  contract tests.
- Phase 4 integration: regenerated latest reports and trade tickets are now
  ignored rather than tracked. Maintained decision records and historical
  evidence remain intact. Further indicator-window, blend-weight, or tree
  parameter tuning on the observed windows is stopped; data and information
  quality take priority.

### 2026-07-29: Fixed LightGBM vs XGBRanker 10D Comparison

- Phase 2 research validity: one fixed true XGBoost `rank:ndcg` candidate was
  added beside the existing LightGBM LambdaRank candidate. Both receive the
  same processed daily rank target, daily groups, feature set, five-gain
  target, 100-round budget, 10-session embargo, and raw OOS 10D returns.
- Phase 2 result: across four complete 2024H1--2025H2 windows, LightGBM
  produces mean ICIR .3587, mean Rank IC .0488, 65.04% compounded relative
  QQQ excess, and -27.34% worst drawdown. XGBoost produces mean ICIR .3497,
  mean Rank IC .0406, 70.35% relative excess, and -25.63% worst drawdown.
  XGBoost beats QQQ in 4/4 windows; LightGBM does so in 3/4. The algorithm
  difference is modest compared with the shared drawdown problem.
- Phase 3 governance: the canonical executor now loads complete raw benchmark
  returns per window and fails closed on missing dates. Stability summaries
  include compounded relative excess and require positive benchmark economics.
  Neither ranker passes the drawdown or ready-ratio gate; the decision is
  `rejected`, `stable_research_candidate=false`, and `trade_ready=false`.
- Phase 1 limitation: the 126-symbol comparison uses a static curated universe
  aligned to common coverage from 2021-04-05 and therefore retains explicit
  survivorship bias. The only approved next model-family check is the same
  frozen comparison on window-start point-in-time membership, not parameter
  tuning.
