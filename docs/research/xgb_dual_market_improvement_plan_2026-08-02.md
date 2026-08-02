# Dual-market XGBoost baseline verification and improvement plan

## Decision context

The user designated two historical XGBoost results for follow-up:

- approximately 81.43% compounded excess relative to QQQ;
- approximately 20.18% compounded excess relative to CSI 300.

These figures do not match the currently documented 126-symbol US ranker comparison, which records 70.35% XGBoost relative excess. They are therefore separate baseline claims until their original artifacts and experiment identities are recovered.

The study is governed by Issue #338 and
`configs/research_paradigms/xgb_dual_market_improvement_v1.yaml`.

## Workstream ownership

The assigned research agent acts as a quantitative model-validation owner, not as an unrestricted optimizer. It owns:

1. baseline provenance and exact reproduction;
2. performance and risk attribution;
3. a bounded, pre-registered improvement ladder;
4. immutable evidence and experiment-ledger updates;
5. a market-specific stop or continue recommendation.

US and CN evidence must never be pooled into one promotion decision.

## Execution sequence

### 0. Recover the exact baseline

Run:

```bash
uv run python scripts/audit_xgb_baseline_provenance.py \
  --output artifacts/evidence/xgb_baseline_provenance_report.json
```

A token match is only a lead. Verification requires the original provider manifest, universe, dates, feature set, label, XGBoost parameters, portfolio construction, costs and output manifest.

If no exact artifact survives, reconstruct the closest frozen experiment once and label it `baseline_reconstructed`.

### 1. Replicate before changing anything

Run each baseline unchanged on its governed market scope:

- US 87, benchmark QQQ;
- CN 130, benchmark CSI 300.

No selected symbol may be silently excluded. A provider or lifecycle failure produces `baseline_data_blocked` rather than a smaller opportunistic universe.

### 2. Diagnose improvement headroom

The diagnostic report must separate:

- signal quality: IC, Rank IC, decay and Top-Bottom spread;
- model stability: seeds, bootstrap, feature importance and score stability;
- economic conversion: turnover, concentration, costs and Top-K overlap;
- hidden exposures: sector, size, beta and volatility;
- failure concentration: dates, regimes, names and drawdown episodes.

The report must identify whether the likely bottleneck is data, information content, XGBoost regularization, portfolio construction or risk control.

### 3. Register variants before observing the final challenge

The development budget is capped at 12 variants per market. The exact variant grid and final challenge dates must be committed before candidate results are inspected.

The permitted ladder is:

1. data-quality-only;
2. pre-declared factor-family additions, including governed Alpha158 groups and PIT fundamentals after coverage gates;
3. one bounded XGBoost objective/regularization comparison;
4. portfolio-construction efficiency;
5. market-state or risk overlay using reference assets outside the stock rank.

Factor-family ablations are mandatory. A large factor count is not evidence of improvement.

### 4. Freeze one candidate and challenge once

One candidate per market may enter the untouched challenge window. It is accepted only when relative excess improves without an unacceptable drawdown, concentration, turnover or multiple-testing trade-off.

## Required conclusions

Each market must finish with exactly one decision:

- `improvement_supported`;
- `baseline_only`;
- `not_reproducible`;
- `data_blocked`.

`improvement_supported` remains a research status. It does not set `trade_ready=true`.

## Relationship to PR #289

PR #289 remains the frozen selected-pool retest for the separately documented 70.35% US XGBoost reference. This workstream may reuse its provider and reporting infrastructure, but it must not overwrite the 81.43% / 20.18% provenance question or present the two baselines as the same experiment.
