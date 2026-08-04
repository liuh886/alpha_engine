# BYD SMA ATR claim evidence

## Governed decision

`improved_but_not_outperforming`

The original 0%/100% rule is not supported as an outperforming BYD strategy. A permanent core position materially improves it, but the frozen family does not beat canonical V1.0 or buy-and-hold under the Issue #521 contract.

## Exact data identity

- canonical snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- adjusted OHLCV SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- cutoff: `2026-08-03`

## Reproducible workflow evidence

- workflow: `BYD SMA ATR Claim Verification`
- run ID: `30930210360`
- artifact ID: `8900834854`
- artifact name: `byd-sma-atr-claim-evidence`
- artifact ZIP SHA-256: `4ea5d72164de0d49719a46f02863016f09a8957b839e0a3c0d407d9640caad3b`

The artifact contains:

- `summary.json`
- `report.md`
- `candidate_development_ranking.csv`
- `evaluation_metrics.csv`
- `selected_daily.csv`
- `selected_trades.csv`
- `selected_signal_log.csv`
- `tactical_episodes.csv`
- `period_concentration.csv`
- `annual_returns.csv`
- `claimant_same_close_daily.csv`

## Key numbers

| Model | Full CAGR | Full MDD | Full Calmar | 2023–2024 return | 2025+ return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original next-open 0/100 | 8.74% | -50.95% | 0.1715 | 9.57% | 5.36% |
| Core 50 / ATR 3.2 | 15.62% | -44.01% | 0.3548 | 12.21% | 5.69% |
| Core 75 / ATR 3.2 | 18.16% | -49.54% | 0.3665 | 12.55% | 4.86% |
| Development-ranked Core 75 / ATR 3.6 | 18.02% | -50.10% | 0.3596 | 9.59% | 2.50% |
| Canonical V1.0 | 19.58% | -53.69% | 0.3647 | 12.05% | 6.83% |
| Buy-and-hold | 20.04% | -56.22% | 0.3564 | 12.22% | 3.40% |

## Gate result

Passed:

- full-history Calmar above buy-and-hold for the development-ranked diagnostic;
- fixed-validation drawdown better than buy-and-hold;
- turnover below three round trips/year after adding a 75% core;
- no single positive tactical episode exceeded 50% of all positive episode benefit.

Failed:

- development selection CAGR gate;
- full-history CAGR above buy-and-hold and V1.0;
- full-history Calmar above V1.0;
- fixed-validation return above both comparators;
- retrospective 2025+ return within one point of V1.0;
- 40 bps full-history CAGR above V1.0;
- cross-period positive relative-return diversification.

- `research_only=true`
- `trade_ready=false`
