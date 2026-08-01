# QQQ/TQQQ realized downside-volatility veto v4.2 result

Date: 2026-08-01

Experiment: `qqq_tqqq_downside_vol_veto_v4_2`

Status: `research_only=true`, `trade_ready=false`

## Decision

Reject the QQQ realized downside-volatility veto.

The factor reduced annual volatility by only 0.03 percentage points while reducing CAGR, Sharpe, Sortino and Calmar. Maximum drawdown, switch count, turnover and transaction cost were unchanged. It did not improve the complete portfolio and provided no clear incremental value beyond the frozen VIX/VXN architecture.

Do not add this factor to v4.1. Do not search alternative downside-volatility windows, quantiles, definitions or persistence rules on the same sample.

## Frozen factor

The challenger used exactly one predeclared signal:

- adjusted close-to-close QQQ returns;
- annualized root mean square of negative returns over ten sessions;
- stress when the current value exceeded its trailing 252-session 80th percentile, using at least 126 observations.

The factor only vetoed or exited the leveraged state. QQQ defense, price repair, VIX, VXN, the 75% TQQQ weight, close signal, next-open execution and transaction costs were unchanged.

## Full-sample result

Economic sample: 2011-05-02 through 2026-07-30; 3,834 observations.

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|
| Frozen v4.1 | **26.17%** | 26.11% | **1.022** | **1.453** | -38.58% | **0.678** | **3,333.44%** |
| v4.1 + downside-volatility veto | 25.95% | **26.07%** | 1.016 | 1.443 | -38.58% | 0.672 | 3,243.92% |

Relative to v4.1:

- CAGR: -0.22 percentage points;
- annual volatility: -0.03 percentage points;
- Sharpe: -0.006;
- Sortino: -0.009;
- maximum drawdown: unchanged;
- Calmar: -0.006;
- total return: -89.53 percentage points over the common sample;
- average TQQQ weight: -0.18 percentage points;
- switches: unchanged at 92;
- turnover: unchanged at 139 units.

The factor failed the predeclared requirement for a material false-start or tail-risk improvement.

## Incremental-information test

Across the prepared sample:

- downside-volatility stress sessions: 838;
- VXN stress sessions: 841;
- downside stress overlapping VXN: 575 sessions, or 68.6% of downside-stress observations;
- downside stress unique versus both VIX and VXN: 235 sessions, or 28.0%.

The factor was not completely redundant, but the unique observations did not translate into useful portfolio changes.

## Transition attribution

The challenger changed only nine transition dates and nine economic holding sessions. All nine changes blocked a leveraged entry that v4.1 would have allowed.

Notable examples:

- 2015-10-09: the blocked TQQQ exposure subsequently gained about 17.1% over ten sessions and 22.2% over twenty sessions;
- November 2020: repeated blocked sessions preceded positive TQQQ returns over ten, twenty and forty sessions;
- 2024-09-13: TQQQ subsequently gained about 7.9% over ten sessions and 13.9% over twenty sessions;
- 2026-04-09: TQQQ subsequently gained about 23.7% over ten sessions and 47.5% over twenty sessions.

The veto avoided losses on a few individual next-open sessions, but six of the nine changed economic sessions reduced return. The sum of changed-session challenger-minus-baseline return differences was approximately -2.47 percentage points.

## Chronological stability

| Period | v4.1 CAGR | Downside-veto CAGR | v4.1 Sharpe | Downside-veto Sharpe | Result |
|---|---:|---:|---:|---:|---|
| 2011-2017 | 18.74% | 18.89% | 0.940 | 0.947 | Challenger slightly better |
| 2018-2021 | **43.71%** | 42.47% | **1.322** | 1.297 | Challenger weaker |
| 2022-2026 | **22.97%** | 22.96% | 0.870 | 0.870 | Effectively unchanged |

The small early improvement was outweighed by weaker results in 2018-2021 and no meaningful recent improvement.

## Stress windows

The strategies were identical during:

- 2018 Q4;
- the 2020 crash/recovery window;
- the 2022 drawdown.

The factor therefore did not improve any of the predeclared major stress windows.

## Rolling stability

Among rolling windows actually affected by the factor:

- only about 39% of one-year windows had higher CAGR, Sharpe or Calmar;
- about 38% of three-year windows had higher CAGR;
- median affected rolling CAGR, Sharpe and Calmar differences were negative.

This confirms that the factor did not provide stable incremental value.

## Cost sensitivity

The challenger remained weaker at 10, 25 and 50 bps transaction-cost assumptions. Because switch count and turnover were unchanged, costs did not alter the conclusion.

## Interpretation

Realized downside volatility is conceptually distinct from option-implied volatility, but this frozen rule was too late or too persistent during several profitable recovery episodes. It mainly blocked leverage after recent negative returns had already occurred, when the price-repair state was beginning to capture the rebound.

A plausible narrative is not enough. Since the full portfolio did not improve, the factor is rejected without refinement.

## Next step

Keep v4.1 unchanged and proceed to the final predeclared independent candidate: one liquid credit-risk proxy, subject first to data-quality and interpretation checks. The credit factor must remain a leverage-layer veto and must demonstrate clear incremental value beyond price, VIX and VXN.

## Evidence

- workflow run: `30693357139`;
- artifact ID: `8816439747`;
- evidence digest: `sha256:f051722493f8f1e8ad7caca9c7016436bc85da6486110a8d3eed3ece8762a02e`.
