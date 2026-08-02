# US87 XGBoost bounded optimization result

## Decision

`improvement_supported` for research continuation; `trade_ready=false`.

The bounded development grid selected a risk-adjusted momentum feature group with stronger XGBoost regularization. The candidate improved the frozen 2026H1 challenge return and ranking diagnostics relative to the immutable US87 baseline, but did not improve drawdown. It therefore becomes the next research candidate, not a trade-ready model.

## Evidence identity

- PR: #343
- Workflow run: `30733686862`
- Artifact: `8828827295`
- Artifact digest: `sha256:69e4faf8e30fdc50647a272ba26ccfbc64aa42b52a25c935af49bf236d0755a4`
- Provider cutoff: 2026-07-31
- Development windows: 2024H1, 2024H2, 2025H1, 2025H2
- Frozen challenge: 2026H1
- Development variants attempted: 6

## Frozen candidate

- Feature group: `risk_controlled_momentum`
- XGBoost calibration:
  - gain bins: 7
  - boosting rounds: 200
  - leaves: 31
  - minimum leaf data: 20
  - learning rate: 0.03
- Strategy: Top-15 equal weight, 10-session holding/rebalance
- Cost convention: unchanged inherited 20 bps portfolio cost

## Development evidence

| Metric | Selected candidate |
|---|---:|
| Compounded strategy return | 233.09% |
| Compounded QQQ return | 55.20% |
| Compounded relative excess | 114.62% |
| Mean ICIR | 0.2273 |
| Mean Rank IC | 0.0404 |
| Mean Top-Bottom spread | 1.95% |
| Positive excess windows | 4/4 |
| Worst drawdown | -28.36% |

The candidate improves development-period relative excess versus the frozen baseline, but the drawdown remains too large for promotion.

## Frozen 2026H1 challenge

| Metric | Optimized candidate | Frozen baseline | Difference |
|---|---:|---:|---:|
| Total return | 103.69% | 92.97% | +10.72 pp |
| QQQ return | 15.51% | 15.51% | — |
| Simple excess | 88.18% | 77.46% | +10.72 pp |
| ICIR | 0.8400 | 0.6824 | +0.1576 |
| Rank IC | 0.1589 | 0.1361 | +0.0228 |
| Top-Bottom spread | 8.74% | 8.22% | +0.52 pp |
| Maximum drawdown | -6.80% | -6.12% | -0.68 pp |
| Turnover units | 5.77 | 6.17 | -0.40 |

The pre-registered acceptance rule passes through return improvement and positive challenge ICIR/Rank IC. The candidate does not pass through drawdown improvement.

## Interpretation

The result supports a real model improvement rather than a score-only relabeling:

- challenge excess, ICIR, Rank IC and Top-Bottom spread all improve;
- turnover declines modestly;
- the score direction remains aligned;
- the 2026H1 result was observed only after the candidate was frozen.

However, the result is still concentrated in a high-beta growth and semiconductor opportunity set. The leading selected names include AEHR, POET, MU, WDC, INTC, MRVL, PLTR, AAOI and COHR. Security- and sector-contribution attribution remains mandatory before any promotion decision.

## Next gate

The optimized candidate may proceed to contribution concentration, seed/bootstrap stability and cost stress testing. It must not be promoted unless:

1. leave-one-security and leave-one-sector results remain positive;
2. the 2026H1 uplift is not dominated by a few names;
3. seed and block-bootstrap Top-15 overlap is stable;
4. higher-cost stress does not erase the improvement;
5. maximum drawdown improves on broader evidence or is controlled by a separately tested risk overlay.
