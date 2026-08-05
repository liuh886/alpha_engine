# BYD v1.2 capped trend-expansion research

- Governed decision: `retain_byd_v1_1`
- Overlap: `2019-11-26` to `2026-08-03`
- Expansion entry signals: `80`
- Expansion active sessions: `86`
- Completed expansion episodes: `15`
- Primary costs: 20 bps transitions + 6% annual financing
- Stress costs: 40 bps transitions + 10% annual financing
- Historical freshness: `false`

## Full-overlap primary scenario

| model                         |     cagr |   total_return |   max_drawdown |   calmar |   round_trips_per_year |   financing_cost_paid |
|:------------------------------|---------:|---------------:|---------------:|---------:|-----------------------:|----------------------:|
| byd_v1_1                      | 0.350728 |        5.81814 |      -0.487392 | 0.719602 |                1.05718 |            0          |
| byd_v1_2_trend_expansion_1125 | 0.356613 |        6.01003 |      -0.498772 | 0.714981 |                1.6445  |            0.00255952 |
| byd_v1_2_trend_expansion_1100 | 0.355452 |        5.97183 |      -0.49651  | 0.715901 |                1.52704 |            0.00204762 |
| byd_v1_2_trend_expansion_1250 | 0.362295 |        6.19963 |      -0.509976 | 0.710416 |                2.23182 |            0.00511905 |

## Frozen gates

```json
{
  "cagr_improves_1pp": false,
  "calmar_decline_le_0_02": true,
  "max_drawdown_worsening_le_3pp": true,
  "minimum_10_episodes": true,
  "minimum_126_financed_sessions": false,
  "no_more_than_one_negative_period": true,
  "positive_contribution_not_concentrated": false,
  "robustness_improves_primary_and_stress_return": true,
  "round_trips_per_year_le_3": true,
  "stress_total_return_above_baseline": true
}
```

## Diagnostics

```json
{
  "baseline_stress_total_return": 5.63657541510138,
  "baseline_total_return": 5.818140854238716,
  "cagr_delta": 0.005884494395869355,
  "calmar_delta": -0.0046209783309549834,
  "completed_expansion_episodes": 15,
  "financed_sessions": 86,
  "max_drawdown_delta": -0.01138033097399016,
  "max_positive_contribution_share": 0.7975291089418095,
  "negative_periods": 0,
  "primary_financing_cost_paid": 0.0025595238095238097,
  "primary_stress_total_return": 5.710191335675922,
  "primary_total_return": 6.010033972810264
}
```
