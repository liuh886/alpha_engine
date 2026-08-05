# BYD defensive-sleeve convergence screen

- Governed decision: `retain_515180_as_only_prospective_etf`
- Selected challenger: `None`
- Common overlap: `2019-11-26` to `2026-08-03`
- Common sessions: `1610`
- Common eligible opens: `1598`
- Blocked candidates: `{"512890.SH": {"cutoff": "2026-08-03", "error": "provider OHLC envelope violations exceed tolerance: 2024-03-29", "error_type": "RuntimeError", "provider_envelope_audit_preserved": true, "provider_reference_preserved": true, "status": "data_blocked", "symbol": "512890.SH"}}`
- Execution: prior-close V1.0 target, next all-assets common eligible open
- Costs: 20 bps primary, 40 bps stress
- Period contribution: relative terminal wealth versus cash
- Historical freshness: `false`
- Research only: `true`

## Full-overlap 20 bps ranking

| candidate   |     cagr |   total_return |   max_drawdown |   calmar |   round_trips_per_year |
|:------------|---------:|---------------:|---------------:|---------:|-----------------------:|
| 515180.SH   | 0.350728 |        5.81814 |      -0.487392 | 0.719602 |                1.05718 |
| 511010.SH   | 0.338731 |        5.4406  |      -0.485378 | 0.69787  |                1.05718 |
| cash        | 0.335234 |        5.33394 |      -0.489782 | 0.684455 |                1.01802 |

## Period-relative contribution

| candidate   | window                  |   incremental_total_return |   positive_contribution_share |
|:------------|:------------------------|---------------------------:|------------------------------:|
| 515180.SH   | development             |                 0.0195068  |                      0.261492 |
| 515180.SH   | fixed_validation        |                 0.0275033  |                      0.368687 |
| 515180.SH   | retrospective_2025_plus |                 0.0275879  |                      0.369821 |
| 511010.SH   | development             |                 0.005293   |                      0.315779 |
| 511010.SH   | fixed_validation        |                 0.00956197 |                      0.570464 |
| 511010.SH   | retrospective_2025_plus |                 0.00190677 |                      0.113757 |

## Frozen gates

```json
{
  "511010.SH": {
    "cash_gates": {
      "all_three_periods_positive": true,
      "cagr_delta_at_least_50bp": false,
      "calmar_not_below_cash": true,
      "drawdown_not_worse_by_more_than_1pp": true,
      "max_period_share_at_most_60pct": true,
      "round_trips_at_most_3": true,
      "stress_total_increment_nonnegative": true
    },
    "cash_qualified": false,
    "challenge_gates": {},
    "challenge_qualified": false,
    "data_status": "canonical_pass"
  },
  "512890.SH": {
    "blocker": {
      "cutoff": "2026-08-03",
      "error": "provider OHLC envelope violations exceed tolerance: 2024-03-29",
      "error_type": "RuntimeError",
      "provider_envelope_audit_preserved": true,
      "provider_reference_preserved": true,
      "status": "data_blocked",
      "symbol": "512890.SH"
    },
    "cash_gates": {},
    "cash_qualified": false,
    "challenge_gates": {},
    "challenge_qualified": false,
    "data_status": "blocked"
  },
  "515180.SH": {
    "cash_gates": {
      "all_three_periods_positive": true,
      "cagr_delta_at_least_50bp": true,
      "calmar_not_below_cash": true,
      "drawdown_not_worse_by_more_than_1pp": true,
      "max_period_share_at_most_60pct": true,
      "round_trips_at_most_3": true,
      "stress_total_increment_nonnegative": true
    },
    "cash_qualified": true,
    "challenge_gates": {},
    "challenge_qualified": false,
    "data_status": "canonical_pass"
  }
}
```
