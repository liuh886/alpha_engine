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

All variants charge 20 bps against cash-inclusive one-way turnover.  This counts
the full funded entry and correctly charges exposure changes such as 1.0 to 0.5
or 0.5 to 1.0; cash is not treated as a free source or destination of exposure.

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

## Local OOS result

The July 24, 2026 local watchlist run covered the same four half-year OOS
windows as the baseline.

| Variant | Positive excess windows | Compounded relative excess | Worst drawdown | Mean window Sharpe | Gate |
|---|---:|---:|---:|---:|---|
| `top5_equal_weight` | 4 / 4 | 52.02% | -22.94% | 2.52 | fail |
| `top3_inverse_vol20_weight` | 4 / 4 | 49.16% | -15.07% | 2.14 | fail |
| `top3_benchmark_trend_filter` | 4 / 4 | 40.61% | -14.27% | 2.09 | pass |

The benchmark-trend filter is selected as `candidate_v2` because it is the only
variant that satisfies all three gates.  Relative excess and Sharpe are lower
than the frozen baseline, so this is a drawdown-control improvement rather than
an alpha improvement.  It remains a stronger research candidate and is not
trade-ready.

## Interpretation boundary

This experiment is not a new alpha discovery search.  It is a risk-control test
around an already preserved candidate.  The runner must not tune parameters, add
new factors, change the universe, or alter the frozen blend score.
