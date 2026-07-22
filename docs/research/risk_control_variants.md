# Risk-Control Variants for `us_top3_blend_v1`

This document defines the next controlled experiment after preserving
`us_top3_blend_v1` as the canonical baseline.

## Baseline problem

The baseline from PR #172 is a stronger research candidate, but not trade-ready:

- US / QQQ
- 50/50 daily ranker + inverted historical 10D momentum
- raw forward 10D returns
- Top-3 long-only
- 20 bps cost
- 4/4 positive OOS excess windows
- 57.87% compounded relative excess
- worst drawdown: -17.00%

The drawdown breaches the -15.00% gate.  This experiment changes only portfolio
construction, not the score, universe, benchmark, cost assumption, factor set, or
model weights.

## Approved variants

The runner evaluates exactly three variants:

1. `top5_equal_weight`
   - Purpose: reduce concentration by increasing holdings from 3 to 5.
   - Weighting: equal weight.
   - Gross exposure: 1.0.

2. `top3_inverse_vol20_weight`
   - Purpose: retain the Top-3 signal but reduce exposure to high-volatility names.
   - Weighting: inverse 20-session realized volatility.
   - Gross exposure: 1.0.

3. `top3_benchmark_trend_filter`
   - Purpose: reduce drawdown during weak benchmark regimes.
   - Weighting: equal weight Top-3.
   - Gross exposure: 1.0 when QQQ 20D trend is non-negative; 0.5 when QQQ 20D trend is negative.

## Runner

```bash
uv run python scripts/run_risk_control_variants.py \
  --root . \
  --first-test-year 2024 \
  --last-test-year 2026
```

Expected outputs:

```text
artifacts/evidence/risk_control_variants/aggregate_summary.json
artifacts/evidence/risk_control_variants/evidence_manifest.json
artifacts/evidence/risk_control_variants/per_window/*.json
```

## Candidate v2 gate

A variant may become `candidate_v2` only if all conditions are true:

- positive excess windows >= 3
- compounded relative excess return > 30%
- worst drawdown >= -15%

The output remains research-only.  `trade_ready` must remain false.

## Interpretation boundary

This experiment is not a new alpha discovery search.  It is a risk-control test
around an already preserved candidate.  The runner must not tune parameters, add
new factors, change the universe, or alter the frozen blend score.
