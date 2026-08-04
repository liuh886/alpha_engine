# BYD V1.1 momentum-factor and XGBoost evidence

## Status

- Final research decision: `byd_v1_1_xgb_not_supported`
- PR: `#504`
- Issue: `#503`
- Evidence run: `30879667536`
- Evidence artifact: `8880822242`
- Artifact ZIP SHA-256: `37b663b859c97404eddd5aeace6baa4763da7cfb1072a3cb1aad40a7aff2a06f`
- Model family: expanding walk-forward XGBoost regression
- Objective: `reg:squarederror`
- Target: next-open to ten-session-later-open return
- Status: `research_only=true`, `trade_ready=false`

BYD V1.0 is not an XGBoost model. It remains a deterministic 75%/100% rule baseline and did not beat BYD buy-and-hold over 2012–2024.

## Frozen model contract

- decision every 10 sessions;
- refit every 20 sessions;
- minimum 756 training samples;
- expanding training window;
- 10-session label embargo;
- 300 boosting rounds;
- fixed depth, regularization, subsample, and column-sample parameters;
- no random split, grid search, validation-driven feature selection, or same-close execution;
- 20 bps primary transaction cost and 40 bps stress cost.

## Fixed 2023–2024 validation

| Strategy | Total return | CAGR | Max drawdown | Calmar |
| --- | ---: | ---: | ---: | ---: |
| BYD buy-and-hold | 12.48% | 6.31% | -47.12% | 0.1340 |
| BYD V1.0 rule baseline | 12.38% | 6.26% | -42.57% | 0.1471 |
| Best development-only single factor | 11.07% | 5.62% | -23.93% | 0.2347 |
| Constant 75% BYD | 11.53% | 5.85% | -37.47% | 0.1561 |
| XGB binary 0/100 | 5.82% | 2.99% | -25.06% | 0.1193 |
| XGB core 75/100 | 12.13% | 6.14% | -41.98% | 0.1463 |
| XGB four-state | **14.99%** | **7.54%** | **-35.67%** | **0.2114** |

The four-state mapping was the only mapping to pass every frozen validation gate. It used 0%, 50%, 75%, or 100% BYD according to the fixed predicted-return thresholds.

## Prediction quality through 2024

- OOS samples: 219;
- Spearman correlation: 0.0905;
- Pearson correlation: 0.0305;
- direction hit rate: 54.79%;
- seven calendar years had hit rate above 50%;
- maximum mean feature gain share: 7.27%, below the 40% concentration cap.

This is weak but non-zero predictive evidence. The model did not depend on one dominant feature.

## 2025–2026-08-03 retrospective holdout

The validation winner failed the holdout contradiction test:

| Metric | XGB four-state | BYD V1.0 rule |
| --- | ---: | ---: |
| Total return | -1.30% | 7.09% |
| CAGR | -0.86% | 4.63% |
| XGB max drawdown | -30.41% | — |
| XGB 40 bps total return | -2.87% | — |

Failed gates:

- positive holdout return;
- CAGR not below V1.0;
- total return not below V1.0;
- positive return at 40 bps.

Therefore the validation winner cannot be promoted, and the final result remains `byd_v1_1_xgb_not_supported`.

## Momentum-factor findings

The clearest result is that BYD's useful 10-session information is not conventional trend-following momentum. The more stable factors mostly point to **medium/long-horizon reversal and drawdown recovery**.

| Factor | Economic orientation | Development Spearman | Validation Spearman | Holdout Spearman | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| `drawdown_120` | deeper drawdown is more constructive | 0.0834 | 0.0790 | 0.2242 | strongest cross-period reversal evidence |
| `drawdown_252` | deeper drawdown is more constructive | 0.1275 | 0.0492 | 0.0634 | stable but weak long-drawdown recovery signal |
| `distance_from_low_20` | stronger rebound from recent low | 0.1017 | 0.1284 | 0.0908 | positive rank relation, but weak standalone economic monotonicity |
| `trend_slope_120` | weaker prior long trend is more constructive | 0.0920 | 0.0362 | 0.0498 | long-horizon reversal rather than continuation |
| `mom_120` | weaker 120-day momentum is more constructive | 0.0663 | 0.0263 | 0.1968 | another reversal signal |
| `mom_2` | very short momentum continuation | 0.0746 | 0.0461 | 0.0216 | only short-horizon continuation signal with consistent sign |

These factors are candidates for future **state-conditioned** research, not standalone trading rules. Several have positive rank correlation but weak or contradictory quintile spreads and direction hit rates, so none is yet strong enough to name as a dedicated BYD factor model.

## Data boundary

- BYD provider: AkShare/Eastmoney qfq;
- rows: 3,654;
- range: 2011-06-30 to 2026-08-03;
- BYD SHA-256: `652c1943d844ecb2bb79f832d6f2f320451dce262b9d810cd502304c194212b9`.

CSI300-relative features were pre-registered but could not be enabled:

- Yahoo history failed the repository OHLC consistency envelope;
- AkShare/Eastmoney index requests were closed by the upstream server;
- the repository's existing `data/csv_source/000300.csv` ends on 2026-06-25 and cannot be silently extended or substituted;
- no tracking ETF was used as a replacement.

The evidence therefore represents the complete BYD-only momentum model. CSI300-relative research remains data-blocked rather than implicitly omitted.

## Latest frozen snapshot

After the 2026-08-03 close:

- predicted next-10-session return: -0.07%;
- binary mapping target: 0% BYD;
- core mapping target: 75% BYD;
- four-state mapping target: 50% BYD.

These are research outputs, not orders or personal investment advice.

## Research conclusion

XGBoost was useful as a diagnostic nonlinear combiner and produced a real validation improvement, but the advantage did not survive the 2025+ regime. The immediate next step should not be a parameter grid around the failed model. Further work requires either:

1. a governed exact-cutoff CSI300/sector benchmark data product so the pre-registered relative features can be tested; or
2. a new, separately frozen state-conditioned hypothesis built around drawdown recovery versus trend continuation, evaluated on future prospective evidence rather than reusing the same holdout for tuning.
