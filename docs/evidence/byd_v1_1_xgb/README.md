# BYD V1.1 momentum-factor and XGBoost evidence

## Final status

- Decision: `byd_v1_1_xgb_not_supported`
- PR: `#504`
- Issue: `#503`
- Model family: expanding walk-forward XGBoost regression
- Objective: `reg:squarederror`
- Target: next-open to ten-session-later-open return
- Status: `research_only=true`, `trade_ready=false`

BYD V1.0 is not an XGBoost model. It is a deterministic 75%/100% rule baseline and did not beat BYD buy-and-hold over 2012–2024.

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

## Two exact-cutoff provider runs

The same frozen model was run against two complete, single-provider BYD histories ending on 2026-08-03. The results were materially different.

### Run A — AkShare/Eastmoney qfq

- Workflow run: `30879667536`;
- Artifact: `8880822242`;
- rows: 3,654;
- SHA-256: `652c1943d844ecb2bb79f832d6f2f320451dce262b9d810cd502304c194212b9`.

The four-state mapping passed all 2023–2024 validation gates:

| Strategy | Total return | CAGR | Max drawdown | Calmar |
| --- | ---: | ---: | ---: | ---: |
| BYD buy-and-hold | 12.48% | 6.31% | -47.12% | 0.1340 |
| BYD V1.0 rule | 12.38% | 6.26% | -42.57% | 0.1471 |
| XGB four-state | **14.99%** | **7.54%** | **-35.67%** | **0.2114** |

However, it failed the 2025+ holdout:

- XGB total return: -1.30%;
- V1.0 total return: +7.09%;
- XGB CAGR: -0.86%;
- XGB 40 bps total return: -2.87%.

This run alone was already insufficient for promotion.

### Run B — Yahoo auto-adjusted

- Workflow run: `30880157979`;
- Artifact: `8881014575`;
- artifact ZIP SHA-256: `57a1617cee0c06bc0761a25841c5c00aa9d29a9e268d9304d06faf0404a88b74`;
- rows: 3,663;
- BYD SHA-256: `a5f67fcb90cebbfe95229c847e5a145d57246a012054c61cb668e5add0301dc5`.

No XGBoost mapping passed the fixed validation gates:

| Strategy | Total return | CAGR | Max drawdown | Calmar |
| --- | ---: | ---: | ---: | ---: |
| BYD buy-and-hold | 12.22% | 6.19% | -45.82% | 0.1350 |
| BYD V1.0 rule | 12.05% | 6.11% | -41.39% | 0.1475 |
| XGB binary 0/100 | 11.59% | 5.87% | -24.31% | 0.2416 |
| XGB core 75/100 | 13.40% | 6.76% | -40.17% | 0.1684 |
| XGB four-state | -7.13% | -3.78% | -31.68% | -0.1193 |

Although the core 75/100 mapping beat the two return baselines, the underlying OOS prediction relationship failed its required gate:

- OOS Spearman: -0.0024;
- OOS Pearson: -0.0690;
- direction hit rate: 49.77%;
- only three years above 50% hit rate.

The mapping therefore cannot be promoted as a predictive model.

## Provider-sensitivity diagnosis

The two adjusted histories are not equivalent representations of the same economic return stream:

- common-date open-return correlation is approximately 0.9568;
- mean absolute daily open-return difference is approximately 0.64 percentage points;
- 591 common sessions differ by more than 1 percentage point in open return;
- early AkShare qfq prices are compressed to low, two-decimal values, magnifying rounding error in adjusted returns;
- the provider histories also differ on several suspended or zero-volume sessions.

For example, on 2012-08-06 AkShare qfq close changed by approximately +27.13%, while Yahoo adjusted close changed by approximately +7.22%. This is far too large to treat as harmless provider noise.

Therefore, the positive AkShare validation result is not robust enough to establish a model. The stricter conclusion is rejection until a canonical high-precision adjusted-price product is defined and audited.

## Momentum-factor findings robust across both providers

The factors below retained the same economic orientation and positive time-series Spearman sign in development, validation, and holdout under both histories.

| Factor | Orientation | AkShare validation IC | Yahoo validation IC | AkShare holdout IC | Yahoo holdout IC | Interpretation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `distance_from_low_20` | stronger rebound | 0.1284 | 0.1256 | 0.0908 | 0.0984 | short recovery state |
| `distance_from_low_60` | stronger rebound | 0.0955 | 0.0932 | 0.0141 | 0.0222 | weaker medium recovery state |
| `drawdown_120` | deeper drawdown is constructive | 0.0790 | 0.0678 | 0.2242 | 0.2047 | strongest robust reversal signal |
| `mom_2` | short continuation | 0.0461 | 0.0502 | 0.0216 | 0.0281 | weak very-short momentum |
| `drawdown_252` | deeper drawdown is constructive | 0.0492 | 0.0357 | 0.0634 | 0.0456 | long drawdown recovery |
| `trend_slope_120` | weaker prior slope is constructive | 0.0362 | 0.0291 | 0.0498 | 0.0395 | long-horizon reversal |
| `mom_120` | weaker prior momentum is constructive | 0.0263 | 0.0209 | 0.1968 | 0.1833 | long-horizon reversal |
| `close_to_sma200` | lower long-trend position is constructive | 0.0180 | 0.0106 | 0.0890 | 0.0745 | weak long mean reversion |

The robust picture is not conventional trend-following momentum. BYD's more repeatable 10-session information appears to be a combination of:

1. rebound strength after a recent low;
2. medium/long drawdown recovery;
3. long-horizon reversal;
4. a much weaker two-session continuation component.

These remain factor hypotheses, not standalone trading models. Their absolute ICs are modest, and several lack clean quintile monotonicity or direction hit rates above 50%.

## CSI300-relative feature boundary

CSI300-relative and residual-momentum features were pre-registered but could not be enabled reliably:

- Yahoo index data failed the repository OHLC consistency envelope;
- AkShare index requests were disconnected upstream in the final evidence run;
- the repository's existing `data/csv_source/000300.csv` ends on 2026-06-25 and cannot be used as an exact 2026-08-03 history;
- no tracking ETF or stale index data was substituted.

The workflow records the blocker and executes the complete BYD-only feature contract.

## Latest snapshots are provider-sensitive

The 2026-08-03 close produced different model outputs:

- AkShare run predicted -0.07% over the next ten sessions and mapped to 50% in the four-state rule;
- Yahoo run predicted +0.50% and mapped to 75% in the four-state rule.

Neither output is suitable for execution because the model itself is rejected and the input data product is not yet canonical.

## Research conclusion

The answer to the XGBoost question is negative for the present contract:

- XGBoost can fit a weak nonlinear signal and may look superior in one validation slice;
- the apparent advantage fails either the holdout test or the cross-provider reproducibility test;
- no BYD V1.1 model has yet run robustly enough to beat BYD itself.

The next scientifically valid step is not hyperparameter tuning. It is to establish a high-precision canonical BYD adjusted-price series, reconcile suspended sessions, and then freeze a new state-conditioned hypothesis around drawdown recovery and rebound strength. The existing 2025+ holdout cannot be reused as an untouched promotion window after that redesign.
