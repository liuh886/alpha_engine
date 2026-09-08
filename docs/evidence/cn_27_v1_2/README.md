# CN_27 V1.2 stable-factor low-turnover evidence

## Decision

`CN_27 V1.2` is **historically supported pending prospective validation**.
It is a research-only retrospective candidate and is not trade ready.

- `research_only=true`
- `trade_ready=false`
- `fresh_historical_holdout=false`
- `automatic_promotion_allowed=false`
- final evidence identity:
  `82faef390a89bd5ddf44b38d9b0b6ffb06b595881f27415d222ba4a41d086237`

## What changed

The research evaluated 18 trailing OHLCV factors, ten first-stage robustness
recipes and seven second-stage stability recipes. The final model uses only
factors whose mean 20-session rank IC was positive in at least four of six
chronological folds:

| Factor | Weight | Positive folds |
| --- | ---: | ---: |
| 120-day residual momentum | 18% | 5/6 |
| 20-day risk-adjusted momentum | 16% | 5/6 |
| 120-day trend efficiency | 15% | 4/6 |
| 120-day risk-adjusted momentum | 15% | 4/6 |
| 60-day positive-day share | 14% | 4/6 |
| 120-day trend | 12% | 4/6 |
| 5-day reversal | 10% | 4/6 |

The portfolio holds up to 12 names, rebalances every 30 sessions, retains names
inside a ten-rank exit buffer, allows at most three names per sector and uses
inverse 60-day volatility weights. Equity exposure is scaled from 25% to 75%
using the observable 60-day CSI 300 volatility; the residual is held in
`515180`. Signals use data available at the session close and execute at the
next eligible open. Missing or one-price bars retain the target and retry it on
subsequent sessions.

## Historical results

The full window contains 729 sessions from 2023-09-01 through 2026-09-04.

| Metric | V1.0 | V1.1 recorded | V1.2 |
| --- | ---: | ---: | ---: |
| Total return | 34.15% | 172.35% | 128.43% |
| CAGR | 10.69% | 41.39% | 33.05% |
| Annual volatility | 22.54% | 27.20% | 24.09% |
| Sharpe, log excess | 0.369 | 1.215 | 1.118 |
| Maximum drawdown | -22.22% | -23.35% | -21.17% |
| Annual one-way turnover | 17.70x | 6.25x | 1.57x |
| Transaction cost paid | 5.20% | 2.56% | 0.53% |

Relative to recorded V1.1, V1.2 reduces annual one-way turnover by about 75%,
reduces maximum drawdown by about 2.18 percentage points and keeps Sharpe above
1. It gives up some historical return in exchange for stability and lower
trading dependence. Doubling all transaction costs leaves full-window Sharpe at
1.110.

All six fixed-model folds have positive Sharpe. Their 25th-percentile Sharpe is
0.765. A two-session execution delay and rebalance phase offsets of 10 and 20
sessions leave the worst full-window Sharpe at 0.957.

The 1,000-sample circular 20-session block bootstrap has a 5th-percentile Sharpe
of 0.246, median 1.115 and 98.8% conditional probability of Sharpe above zero.
Only 58.9% of samples exceed Sharpe 1. This uncertainty estimate is conditional
on the same consumed history and is not a fresh test.

## Expanding-fold walk-forward audit

The audit uses only prior-fold performance when choosing the recipe for the next
fold: f1-f2 select f3, then the training window expands through f6. Strategy
switches incur asymmetric transaction costs from actual previous weights, and
unavailable targets remain pending until tradable.

Across the four validation folds (485 sessions), the stitched result is:

- Sharpe: 1.189
- CAGR: 41.01%
- annual one-way turnover: 1.92x
- maximum drawdown: -21.20%
- positive validation folds: 4/4
- total boundary-transition cost: 0.051%

This is a pseudo-walk-forward robustness audit, not restored historical
freshness: the stable factor set itself was derived from already-consumed V1.2
diagnostics.

## Attribution

Daily gross contribution reconciles to portfolio gross return within
`6.94e-18`. The largest positive single-name contribution share is 10.73%, and
the largest positive single-sector share is 29.44%, below their frozen 35% and
55% limits.

## V1.1 execution audit

V1.1 declared that unavailable trades would be deferred, but its implementation
did not retry residual target differences after the first attempt. Three lock
episodes were present. Replaying the unchanged V1.1 recipe with true retrying
changes full-window Sharpe from 1.215 to 1.240 and annual turnover from 6.25x to
6.30x, so the Sharpe target remains supported, but the original V1.1 evidence
must retain this execution-semantics caveat. V1.1 files were not rewritten.

## Reproduction

Run from the repository root in order:

```powershell
python scripts/run_cn_27_v1_2_discovery.py
python scripts/run_cn_27_v1_3_stability_discovery.py
python scripts/run_cn_27_v1_2.py
```

The first command reproduces the robustness search, the second reproduces the
stability-only search, and the third rebuilds the final model, attribution and
walk-forward evidence. The corresponding evidence identities are
`71e1271a...3bdc`, `15a47ac6...6975` and `82faef39...6237`.

## Promotion boundary

No historical data remains fresh for this pool. V1.2 requires at least 12 months
of unchanged prospective validation after 2026-09-04. Pool membership, factors,
weights, exposure rules, costs and gates must remain frozen throughout that
period for the evidence to retain continuity.
