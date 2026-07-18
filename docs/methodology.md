# Research Methodology

> Last updated: 2026-07-18

This document describes the current research methodology for AlphaEngine. It is the
authoritative reference for understanding how research is structured, what the fixed-10D
paradigm requires, how evidence is evaluated, and what gates a candidate must pass before
it can be considered trade-ready.

---

## 1. Core Paradigm: Fixed 10D Horizon

Both CN and US research follow a **fixed 10-trading-day paradigm** declared in versioned
research-paradigm specs under `configs/research_paradigms/`:

| Market | Spec file | Benchmark | Universe source |
|--------|-----------|-----------|-----------------|
| CN | `cn_10d_csi300_baseline.yaml` | CSI 300 (`000300`) | `configs/research_universes/cn_curated_equities_v1.yaml` |
| US | `us_10d_qqq_baseline.yaml` | QQQ | `configs/research_universes/us_curated_equities_v1.yaml` |

### Paradigm invariants

| Property | Value |
|----------|-------|
| Horizon | 10 trading days |
| Holding period | 10 trading days |
| Rebalance cadence | 10 trading days |
| Return expression | `Ref($close, -10) / $close - 1` |
| Return provenance | `raw_forward_return` |
| Research scope | `research_only: true` — no production or trading claim |
| Walk-forward policy | `complete_windows_only` |
| Train embargo | 10 sessions between each training tail and its OOS test window |

### Universes

Both universes use **static curated membership** as of 2026-07-11, which introduces
**survivorship bias**:
- CN: ~200 A-share equities from the CSI 300 pool
- US: ~120 NASDAQ/NYSE equities from the QQQ tracked pool

This is acceptable for exploratory research but is not an unbiased historical estimate.
No model trained on these universes should be treated as trade-ready without additional
delisting-adjusted backtesting.

### Factor libraries

| Market | Library | Groups |
|--------|---------|--------|
| CN | `configs/factor_libraries/cn_ohlcv.yaml` | short_reversal_liquidity, volatility_reversal, price_volume_pressure, balanced_ohlcv |
| US | `configs/factor_libraries/us_ohlcv.yaml` | momentum, momentum_volatility, momentum_volatility_volume, risk_controlled_momentum |

### Candidate grid

Each spec declares a ranker calibration grid (LightGBM LambdaRank with varying
`n_gain_bins`, `num_leaves`, `min_data_in_leaf`, `learning_rate`) and factor baselines.
The grid is evaluated identity-by-identity against the spec's declared evidence contract.

---

## 2. Return Concepts

Two distinct return concepts are used for different purposes:

| Concept | Expression | Provenance | Purpose |
|---------|-----------|------------|---------|
| **Raw canonical 10D return** | `Ref($close, -10) / $close - 1` | `raw_forward_return` | Economic evaluation, backtest scoring, spread analysis |
| **Processed rank training target** | Same-date cross-sectional percentile rank converted to integer gains | `processed_training_target` | LightGBM LambdaRank training objective only |

The raw forward return is the single economic truth. Processed targets are training
artifacts and are **never** used for economic evaluation, backtest scoring, or promotion
decisions.

---

## 3. Walk-Forward Validation

Walk-forward validation uses **expanding half-year out-of-sample windows** with a
10-session embargo between train and test periods.

| Parameter | CN | US |
|-----------|----|-----|
| Train start | 2021-01-01 | 2021-01-01 |
| Test end | 2026-06-18 | 2026-06-18 |
| First test year | 2024 | 2024 |
| Last test year | 2026 | 2026 |
| Min windows | 3 | 3 |
| Train embargo | 10 sessions | 10 sessions |
| Partial window policy | `complete_windows_only` | `complete_windows_only` |

### Required metrics

Walk-forward results are evaluated against these metrics (defined in gate profile
`ten_day_model_gates_v1`):

| Metric | Description |
|--------|-------------|
| `mean_icir` | Mean information coefficient divided by its cross-window standard deviation |
| `mean_rank_ic` | Mean rank-based information coefficient |
| `mean_spread` | Mean spread between top and bottom quintile returns |
| `worst_drawdown` | Worst portfolio drawdown across windows |
| `ready_ratio` | Fraction of windows meeting all readiness criteria |
| `positive_icir_ratio` | Fraction of windows with positive ICIR |
| `positive_spread_ratio` | Fraction of windows with positive spread |

---

## 4. PromotionDecision Gates

The `PromotionDecision` interface (ADR-0005) is the single canonical promotion gate.
It is enforced by `src/research/promotion_decision.py` and evaluates three required
evidence files **before** any promotion recommendation:

| Evidence file | Purpose | Fail-closed status |
|---------------|---------|---------------------|
| `execution_identity.json` | Proves what ran and which contract was executed | `MISSING_EVIDENCE` if absent |
| `data_readiness.json` | Proves data coverage completeness | `MISSING_EVIDENCE` if absent |
| `walk_forward_stability.json` | Proves walk-forward metrics pass thresholds | `MISSING_EVIDENCE` if absent |

The legacy pipeline's `mean_ic > 0.1 → DEPLOY` gate is **retired** (ADR-0007). No
single metric can trigger a promotion decision. All three evidence files must be
present and valid, or the decision is `MISSING_EVIDENCE`.

### Status separation

Execution state and promotion state are separate interfaces:

| Interface | Values | Implication |
|-----------|--------|-------------|
| **Execution** | completed / skipped / failed | Technical outcome only; no quality claim |
| **PromotionDecision.status** | missing_evidence / rejected / research_candidate / stronger_research_candidate / trade_guidance_candidate | Evidence-derived research status |
| **PromotionDecision.trade_ready** | true only for `trade_guidance_candidate` | Research guidance only; never authorizes live or automated trading |

The current diagnostic evidence did not evaluate promotion and contains no
`trade_guidance_candidate` decision.

---

## 5. Current Evidence: 2026-07-16 Diagnostic Run

The latest evidence package is at `docs/evidence/issue-124-current-2026-07-16/`.

| Market | Status | Acceptance | Diagnostics | Diagnostic only |
|--------|--------|:----------:|:-----------:|:---------------:|
| CN | completed | passed | passed | **true** |
| US | completed | passed | passed | **true** |

Both markets completed with exit code 0. The pipeline **never promotes** — all outputs
are factor diagnostics for review only.

### Key evidence links

- [CN/US evidence README](evidence/issue-124-current-2026-07-16/README.md) — full provenance, factor tables, coverage counts
- [CN factor diagnostics](../artifacts/research_runs/cn_10d_csi300_baseline/factor_diagnostics.json) — 23 unique expressions, best oriented ICIR ~0.22 (5d volatility inverted)
- [US factor diagnostics](../artifacts/research_runs/us_10d_qqq_baseline/factor_diagnostics.json) — 9 unique expressions, best oriented ICIR ~0.29 (20d risk-controlled momentum)
- [CN acceptance](../artifacts/research_runs/cn_10d_csi300_baseline/real_market_acceptance.json) — 10 pass, 1 warn (survivorship bias), 0 fail
- [US acceptance](../artifacts/research_runs/us_10d_qqq_baseline/real_market_acceptance.json) — 10 pass, 1 warn (survivorship bias), 0 fail

### Diagnostic flags

| Flag | CN | US |
|------|:--:|:--:|
| `diagnostic_only` | true | true |
| `promotion_eligible` | false | false |
| `trade_ready` | false | false |
| `research_only` | true | true |
| `promotion_evaluated` | false | false |

### Interpretation boundary

These outputs are factor diagnostics, not a deployable model or trading signal.
Factor-library changes, orientation changes, combination research, model fitting,
promotion, or trade readiness require separate reviewed work. **No model is currently
trade-ready.**

---

## 6. Execution: Spec-Bound ResearchWorkflow

All research execution goes through the canonical `ResearchWorkflow` backed by
`SpecBoundResearchWorkflowExecutor` (ADR-0006, ADR-0007).

```
ResearchWorkflow.run(request)
    ↓
SpecBoundResearchWorkflowExecutor.run_step()
    ↓
resolve_spec(request.market)
    ↓
execute_spec_bound_research(spec)
    ↓
execute_spec_bound_runner(spec, adapter)
    ↓
TRAIN → WALK_FORWARD → BACKTEST → PROMOTE
                                     ↓
                             PromotionDecision
                             (evidence-gated, ADR-0005)
```

- Market `cn` resolves to `configs/research_paradigms/cn_10d_csi300_baseline.yaml`
- Market `us` resolves to `configs/research_paradigms/us_10d_qqq_baseline.yaml`
- The legacy research runtime (`LegacyResearchPipelineExecutor`) is **retired** (ADR-0007)
- Free-text `goal` is audit metadata only; it does not change what executes

### Spec resolution safety

Unsupported markets, path traversal attempts, spec/market mismatches, missing files,
and insufficient symbol coverage all fail before any model or data execution.

### ATTRIBUTION step

No standalone attribution artifact exists in the fixed-10D path. The `ATTRIBUTION`
step is explicitly `SKIPPED` during spec-bound execution.

---

## 7. References

| Document | Purpose |
|----------|---------|
| `configs/research_paradigms/cn_10d_csi300_baseline.yaml` | CN fixed-10D paradigm spec |
| `configs/research_paradigms/us_10d_qqq_baseline.yaml` | US fixed-10D paradigm spec |
| `docs/adr/0005-promotion-decision-single-interface.md` | PromotionDecision single interface (ADR-0005) |
| `docs/adr/0006-spec-bound-default-workflow-runtime.md` | Spec-bound default runtime (ADR-0006) |
| `docs/adr/0007-retire-legacy-research-runtime.md` | Legacy runtime retirement (ADR-0007) |
| `docs/evidence/issue-124-current-2026-07-16/README.md` | Latest CN/US diagnostic evidence |
| `src/research/promotion_decision.py` | PromotionDecision implementation |
| `src/research/spec_bound_execution.py` | Spec-bound execution implementation |
| `src/research/workflow.py` | ResearchWorkflow protocol and runner |
| `src/research/spec_bound_workflow_executor.py` | Default executor (ADR-0006) |
