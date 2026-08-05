# BYD v1.2 extreme-defense research

- Governed decision: `retain_byd_v1_1`
- Overlap: `2019-11-26` to `2026-08-03`
- Extreme entry signals: `20`
- Extreme active sessions: `20`
- Completed extreme episodes: `7`
- Costs: 20 bps primary, 40 bps stress
- Historical freshness: `false`

## Full-overlap 20 bps

| model                         |     cagr |   total_return |   max_drawdown |   calmar |   round_trips_per_year |
|:------------------------------|---------:|---------------:|---------------:|---------:|-----------------------:|
| byd_v1_1                      | 0.350728 |        5.81814 |      -0.487392 | 0.719602 |                1.05718 |
| byd_v1_2_extreme_defense_50   | 0.343389 |        5.58502 |      -0.487392 | 0.704543 |                1.60534 |
| byd_v1_2_extreme_defense_625  | 0.347076 |        5.70129 |      -0.487392 | 0.712109 |                1.33126 |
| byd_v1_2_extreme_defense_cash | 0.336978 |        5.38694 |      -0.487392 | 0.69139  |                1.60534 |

## Frozen gates

```json
{
  "cagr_or_calmar_improvement": false,
  "max_drawdown_improves_3pp": false,
  "no_more_than_one_negative_period": false,
  "positive_contribution_not_concentrated": false,
  "robustness_same_direction": false,
  "round_trips_per_year_le_2": true,
  "stress_40bps_not_below_baseline": false
}
```

## Diagnostics

```json
{
  "baseline_20bps_total_return": 5.818140854238716,
  "baseline_40bps_total_return": 5.63657541510138,
  "cagr_delta": -0.0073395849482917885,
  "calmar_delta": -0.015058901512580825,
  "max_drawdown_improvement": 1.1102230246251565e-16,
  "max_positive_contribution_share": 0.0,
  "negative_periods": 2,
  "primary_20bps_total_return": 5.5850231740809555,
  "primary_40bps_total_return": 5.320370917281913
}
```
