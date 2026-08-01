# QQQ/TQQQ HYG/SHY credit-risk veto v4.2 result

Date: 2026-08-01

Experiment: `qqq_tqqq_credit_risk_veto_v4_2`

Status: `research_only=true`, `trade_ready=false`

## Decision

Do not add the HYG/SHY MA50 credit-risk veto to v4.1.

This was the strongest new factor tested in the sequential research cycle: it improved full-sample CAGR, volatility, Sharpe, Sortino and Calmar without increasing switches or turnover. However, the improvement was not stable enough to satisfy the predeclared requirement for an obviously effective factor.

The economic benefit was concentrated in 2012 and especially 2015. The factor was slightly weaker in 2018-2021, slightly weaker in CAGR during 2022-2026, did not change any of the predeclared 2018 Q4, 2020 or 2022 stress windows, and changed no economic holdings after April 2023.

Record the result as a positive but historically concentrated research finding. Keep v4.1 unchanged and do not test alternative Treasury ETFs, moving-average windows, momentum confirmations or persistence rules on the observed sample.

## Proxy and data-quality result

The proxy was:

```text
adjusted close HYG / adjusted close SHY
```

Credit-risk stress was active when the ratio closed below its own MA50. The proxy was treated as high-yield relative risk appetite, not as a pure option-adjusted credit spread.

The predeclared data-quality gate passed:

- common span: 2010-10-18 through 2026-07-31;
- common sessions: 3,970;
- coverage within the prepared common span: 100%;
- missing sessions: 0;
- all adjusted closes positive;
- maximum absolute daily ratio return: 6.51%, below the 20% quality guard.

The experiment therefore failed on stability and attribution, not on data quality.

## Full-sample result

Economic sample: 2010-12-28 through 2026-07-30; 3,920 observations.

| Strategy | CAGR | Volatility | Sharpe | Sortino | Max drawdown | Calmar | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|
| Frozen v4.1 | 26.14% | 25.91% | 1.027 | 1.459 | -38.58% | 0.678 | 3,607.07% |
| v4.1 + HYG/SHY veto | **26.76%** | **25.67%** | **1.053** | **1.499** | -38.58% | **0.694** | **3,897.59%** |

Relative to v4.1:

- CAGR: +0.61 percentage points;
- annual volatility: -0.24 percentage points;
- Sharpe: +0.026;
- Sortino: +0.040;
- maximum drawdown: unchanged;
- Calmar: +0.016;
- total return: +290.52 percentage points over the long sample;
- average TQQQ weight: -0.99 percentage points;
- switches: unchanged at 92;
- turnover: unchanged at 139 units;
- transaction-cost deduction: unchanged.

The full-sample result is directionally attractive and remains positive at 10, 25 and 50 bps transaction-cost assumptions.

## Incremental-information result

Across the prepared sample:

- credit-stress sessions: 1,164;
- VXN-stress sessions: 847;
- credit stress overlapping VXN: 576 sessions, or 49.5% of credit-stress observations;
- credit stress unique versus both VIX and VXN: 550 sessions, or 47.3%.

The factor therefore contained substantial information not already represented by VIX or VXN.

However, unique signal content is not sufficient by itself. It must translate into stable portfolio improvement.

## Chronological stability

| Period | v4.1 CAGR | Credit-veto CAGR | v4.1 Sharpe | Credit-veto Sharpe | Result |
|---|---:|---:|---:|---:|---|
| 2010-2017 | 19.05% | **20.50%** | 0.961 | **1.036** | Credit veto clearly stronger |
| 2018-2021 | **43.71%** | 43.47% | **1.322** | 1.317 | Credit veto slightly weaker |
| 2022-2026 | **22.97%** | 22.90% | 0.870 | **0.875** | Mixed; lower CAGR, slightly higher Sharpe |

The improvement was not repeated consistently across the later validation periods.

## Named stress windows

The strategies were identical during:

- 2018 Q4;
- the 2020 crash and recovery;
- the 2022 drawdown.

The factor therefore did not improve any predeclared major stress window. Its benefit came from other episodes.

## Sparse and concentrated attribution

The factor changed 52 economic holding sessions. Twenty-seven changed sessions added value and twenty-five reduced value. The sum of changed-session return differences was approximately +6.44 percentage points.

Contribution by year:

| Year | Changed sessions | Sum of daily relative contributions |
|---|---:|---:|
| 2012 | 4 | +1.32 pp |
| 2013 | 3 | -0.66 pp |
| 2015 | 20 | +7.00 pp |
| 2019 | 1 | -0.51 pp |
| 2023 | 24 | -0.71 pp |

The positive total was therefore more than fully explained by the 2015 contribution. Excluding 2015, the changed-session contribution was negative.

The factor changed no economic holdings after April 25, 2023. It did not affect the 2024-2026 common QQQI strategy window that produced the current v4.1 result.

## Event interpretation

The HYG/SHY veto was helpful during the April 2012 weakness and especially the November-December 2015 selloff, where blocked TQQQ exposure subsequently suffered material losses.

It was harmful during:

- the October 2015 recovery, when several blocked entries preceded strong TQQQ gains;
- June 2019;
- several February-April 2023 recovery sessions.

The factor therefore distinguished some credit-led weakness but also remained risk-off during profitable equity recoveries.

## Rolling stability

Among rolling windows whose results were actually affected:

- one-year Sharpe improved in about 60% of windows, but CAGR and Calmar improved in only about 44%;
- three-year Sharpe improved in about 67%, but CAGR and Calmar improved in only about 41%;
- median affected one-year and three-year CAGR and Calmar differences were negative;
- mean differences were positive because a small number of large protective episodes dominated.

This is useful tail-risk behavior, but not broad and stable enough for automatic strategy inclusion.

## Cost sensitivity

The credit veto remained better in full-sample CAGR and Sharpe at 10, 25 and 50 bps. Turnover was identical to v4.1, so transaction costs did not explain the improvement.

This strengthens the finding that the factor has real historical information, while not resolving the concentration and stability problem.

## Interpretation

The experiment provides the following durable finding:

> High-yield relative weakness can identify a small number of damaging leveraged periods that VIX and VXN do not capture.

But the evidence does not support the stronger statement:

> HYG/SHY below MA50 is a consistently superior permanent leverage switch.

Under the user's simplicity rule, only the stronger claim would justify adding a factor. That claim is not established.

## Final strategy decision

Keep the strategy unchanged:

- price repair remains the return engine;
- VIX remains the broad risk-budget control;
- VXN remains the Nasdaq-specific leverage veto under prospective monitoring;
- 75% TQQQ remains the frozen leveraged allocation;
- no breadth, downside-volatility, credit or cooldown rule is added.

The next valid work is prospective monitoring, not another retrospective factor transformation.

## Evidence

- workflow run: `30693681032`;
- artifact ID: `8816539805`;
- evidence digest: `sha256:4ba588b36444ff841119b65eb3ebe9a735e80913b75720d163fb56a79a3e9907`.
