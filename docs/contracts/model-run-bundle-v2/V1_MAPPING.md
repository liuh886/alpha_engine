# Formal v1 to Model Run Bundle v2 mapping

This mapping documents the additive compatibility period. It does not alter the accepted v1 package identities or results.

## Common fields

| v1 field | v2 field |
| --- | --- |
| `model_id` | `model_version_id`; family is declared by migration adapter |
| `backtest_id` | source input to immutable `run_id` |
| package/catalog SHA | lineage section and source receipt |
| `evidence_cutoff` | manifest `evidence_cutoff` |
| `date_range` | `comparability_key.start/end` |
| `benchmark` | `comparability_key.benchmark_id` |
| `trace_frequency` | `comparability_key.trace_frequency` |
| `portfolio_contract` | portfolio section plus rebalance/cost contract identities |
| `metrics` | summary canonical metrics with explicit availability |
| `report` | performance section |
| `positions` | portfolio section |
| `trades` | trades section |
| `attribution` | attribution section |
| `window_summary` | robustness section |
| `evidence` | lineage section |
| `evidence_completeness` | section availability declarations |
| `interpretation_notes` | diagnostics interpretation limits |

## QQQ Rotation v4.2

- `model_family_id`: `qqq_rotation`;
- `model_version_id`: `qqqi_qqq_tqqq_v4_2`;
- `model_kind`: `rules_based_allocation`;
- state and transition evidence maps to portfolio/trades, not ranker attribution;
- stock-picking metrics are `not_applicable` unless separately retained by the governed source.

## US x1.1

- `model_family_id`: `us_ranker`;
- `model_version_id`: `us_x1_1`;
- `model_kind`: `cross_sectional_ranker`;
- complete retained performance, positions, trades and attribution map to available sections;
- IC-family metrics map only when the accepted package declares them; absence is `not_computed` or `not_retained`, never a stringified null.

## CN x1.0

- `model_family_id`: `cn_ranker`;
- `model_version_id`: `cn_x1_0`;
- `model_kind`: `cross_sectional_ranker`;
- retained half-year performance and selection snapshots map to performance/portfolio/robustness;
- missing rebalance trades and attribution remain `not_retained` or `blocked_by_source` with the v1 reason;
- migration must not reconstruct daily or rebalance ledgers.

## Canonical metric aliases

| v1 labels | v2 metric ID |
| --- | --- |
| `Total Return`, `total_return` | `total_return` |
| `Annualized Return`, `CAGR`, `annual_return` | `annualized_return` |
| `Benchmark Return`, `benchmark_return` | `benchmark_return` |
| `Compounded Relative Excess Return`, `Excess Return`, `excess_return` | `excess_return` |
| `Annualized Volatility` | `annualized_volatility` |
| `Sharpe Ratio`, `sharpe` | `sharpe_ratio` |
| `Information Ratio` | `information_ratio` |
| `Max Drawdown`, `mdd` | `max_drawdown` |
| `Turnover` | `turnover` |
| `IC` | `ic` |
| `Rank IC` | `rank_ic` |
| `ICIR` | `icir` |

The migration adapter must record the selected source label and estimator semantics; aliasing does not authorize recomputation.
