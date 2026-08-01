# QQQI / QQQ / TQQQ VIX v3 Aggressive Experiment

## Research question

Does increasing TQQQ from 50% to 75% inside the already-confirmed partial-leverage state capture more of the post-shock recovery without an unacceptable deterioration in drawdown and risk-adjusted return?

This is a weight experiment, not a new timing model.

## Frozen comparison

| Element | VIX v2 baseline | VIX v3 challenger |
|---|---:|---:|
| QQQI defensive state | 100% QQQI | 100% QQQI |
| QQQ attack state | 100% QQQ | 100% QQQ |
| Partial-leverage state | 50% QQQ + 50% TQQQ | 25% QQQ + 75% TQQQ |
| Price rules | frozen | identical |
| VIX rules | frozen | identical |
| Close-to-next-open execution | yes | yes |
| Cost model | 10 bps per turnover unit | identical |

The runner fails closed unless the close decision trace and next-open position-state trace are identical between both versions.

## Why 75%, not 100%

The prior VIX v2 result showed that VIX primarily improved tail-risk control rather than generating the return signal. Moving directly to 100% TQQQ would conflate testing a more active recovery allocation with abandoning the partial-leverage risk budget. A 75% challenger is therefore aggressive enough to expose convexity while preserving a 25% unlevered QQQ anchor.

No weight discovered from this sample is eligible for automatic promotion.

## Evaluation

The primary comparison reports:

- total return and CAGR;
- annualized volatility;
- Sharpe and Calmar;
- maximum drawdown;
- turnover and transaction-cost deductions;
- average TQQQ weight;
- cumulative net return earned during the common partial-leverage sessions;
- matched 75% price-repair strategy without VIX, to retain the VIX attribution boundary.

A higher CAGR alone is not a pass. The experiment must show whether the extra recovery capture compensates for deeper false starts, higher volatility and larger turnover costs.

## Persistent research memory

AlphaEngine already stores model training in MLflow and `MLRegistry`, factors in `FactorRegistry`, and walk-forward files under `artifacts/walk_forward/`. Rule-based strategies now use:

- immutable strategy contract: `configs/research_paradigms/*.yaml`;
- reproducible evidence package: `artifacts/evidence/<experiment_id>/`;
- queryable run record: `artifacts/strategy_runs/<experiment_id>/<run_id>/run_record.json`;
- interface: `StrategyExperimentJournal`.

This separates two different research objects:

- trained models: training runs, model artifacts and promotion stages;
- deterministic strategies: frozen rules, backtest evidence, comparisons and decisions.

## Run

```bash
uv run python scripts/run_qqqi_qqq_tqqq_vix_v3_aggressive.py \
  --end-date 2026-08-01
```

Notebook:

```bash
uv run jupyter lab notebooks/14_qqqi_qqq_tqqq_vix_v3_aggressive.ipynb
```

## Status boundary

The true QQQI common sample begins in January 2024. The result remains `research_only=true` and `trade_ready=false`, regardless of whether the 75% challenger outperforms in this observed window.
