# CN_27 V1.1 evidence note

## Decision

`CN_27 V1.1` is **historically supported pending prospective validation**.
It is a research-only retrospective candidate, not a trade-ready model. The
frozen full-window evidence passed every predeclared support gate and reached
the target Sharpe ratio, but the historical pool and all three evaluation
windows have now been consumed by research.

- `research_only=true`
- `trade_ready=false`
- `fresh_historical_holdout=false`
- `automatic_promotion_allowed=false`
- evidence identity:
  `df7149f06de6e1e8b60bcfe7c6f74ce313248aa8bb9a89929c9192f888a007e1`

## Frozen strategy

The selected recipe is `c2_risk_adjusted_momentum`. It combines 20-day and
60-day risk-adjusted momentum, a 60-day trend measure and a 60-day drawdown
measure. The portfolio holds eight names, rebalances every ten sessions, uses a
four-rank exit buffer, limits each sector to two names, applies inverse 20-day
volatility weights, caps a name at 15%, caps equity exposure at 75%, and leaves
the residual in `515180`. Signals use trailing information only and scheduled
orders execute at the next available open.

## Results

The full window contains 729 sessions from 2023-09-01 through 2026-09-04.

| Metric | CN_27 V1.1 | CN_27 V1.0 |
| --- | ---: | ---: |
| Total return | 172.35% | 34.15% |
| CAGR | 41.39% | 10.69% |
| Annual volatility | 27.20% | 22.54% |
| Sharpe, log excess | 1.215 | 0.369 |
| Maximum drawdown | -23.35% | -22.22% |
| Annual one-way turnover | 6.25x | 17.70x |
| Transaction cost paid | 2.56% | 5.20% |
| Average holding count | 8.00 | 1.78 |

The sealed locked-test window covers 246 sessions from 2025-09-01 through
2026-09-04. Its Sharpe ratio is 1.834, annual one-way turnover is 5.98x and
maximum drawdown is -19.38%. Doubling the buy and sell costs leaves the locked
test Sharpe at 1.806 and the full-window Sharpe at 1.183.

Exact return attribution reconciles to daily portfolio returns within
`6.94e-18`. The largest positive single-name contribution share is 16.11%, and
the largest positive single-sector contribution share is 28.74%; both are below
their frozen concentration limits.

## Material caveats

Only one of the four selected factors has the same average rank-IC direction in
the development and selection-validation windows. This is weak factor-level
stability even though the combined portfolio passed its frozen gates. It must
remain visible in every interpretation of these results.

The locked test was sealed before it was opened, but it is no longer fresh.
Neither the high historical return nor the passed stress test establishes live
tradability. The model requires at least 12 months of unchanged prospective
validation after 2026-09-04 before any promotion decision. Pool membership,
factor definitions, rebalance rules, costs and gates may not be changed during
that validation and still claim continuity with V1.1.

## Reproduction

From the repository root:

```powershell
python scripts/run_cn_27_v1_1.py
```

Authoritative outputs are under `artifacts/evidence/cn_27_v1_1/`. The evidence
manifest binds the frozen model contract, pool, source prices, sealed discovery
and holdout manifests, implementations, benchmark inputs and every output hash.
