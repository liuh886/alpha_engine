# LightGBM vs XGBoost Ranker Point-in-Time Robustness

## Decision

The strong static-universe result from the fixed LightGBM/XGBoost comparison
does not survive a stricter NDX membership test. Across four complete
2024H1--2025H2 OOS windows, neither ranker beats QQQ consistently, neither
passes the 0.30 ICIR gate, and both breach the -15% drawdown floor.

The post-identity decision is `rejected`,
`stable_research_candidate=false`, and `trade_ready=false`. The models must not
be used as trading guidance. No model parameters, factor windows, portfolio
sizes, costs, thresholds, or orientations were tuned after seeing the result.

## Frozen comparison contract

- Provider identity:
  `6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407`
- Contract identity:
  `993f36ee044732f00879f6687dc9de070d91292c5a3a1d61b350477f7cff8744`
- Universe: NDX first-trading-day snapshot for each OOS half-year
- Training membership: latest committed semiannual snapshot known on each row
- Actual aligned training start: 2021-04-05 in all four windows
- Target: processed daily cross-sectional rank target
- Economic returns: raw `Ref($close, -10) / $close - 1`
- Benchmark: raw QQQ 10D returns, loaded outside the tradable universe
- Holding/rebalance: 10 trading sessions
- Portfolio: Top-15 equal weight with 20 bps cost; Bottom-15 retained as a
  directional spread diagnostic
- Features: fixed momentum + volatility + volume group
- Calibration: five gains, 100 boosting rounds, learning rate 0.05

The membership source is point-in-time at the OOS window boundary and
semiannual as-of for training. It is not full-daily constituent history.

## Membership coverage

| Window | Snapshot | Requested | Retained | Missing from provider |
| --- | --- | ---: | ---: | --- |
| 2024H1 | 2024-01-02 | 101 | 98 | ANSS, SPLK, WBA |
| 2024H2 | 2024-07-01 | 102 | 100 | ANSS, WBA |
| 2025H1 | 2025-01-02 | 101 | 100 | ANSS |
| 2025H2 | 2025-07-01 | 101 | 100 | ANSS |

Missing symbols are excluded and reported; they are never zero-filled or
replaced with current constituents. The evidence therefore records incomplete
provider coverage and remains research-only.

## Four-window results

| Candidate | Mean ICIR | Mean Rank IC | Mean Top-Bottom spread | Positive excess windows | Compounded total | QQQ | Relative excess | Worst drawdown | Ready ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| XGBoost `rank:ndcg` | 0.1149 | 0.0178 | 0.22% | 1/4 | 2.31% | 55.20% | -34.08% | -25.59% | 0.00 |
| LightGBM LambdaRank | 0.0966 | 0.0175 | 0.33% | 1/4 | 23.40% | 55.20% | -20.49% | -26.11% | 0.25 |
| Historical momentum, original | -0.0052 | 0.0031 | 0.21% | 0/4 | 15.31% | 55.20% | -25.70% | -20.17% | 0.00 |

Compounded values chain the four non-overlapping half-year OOS reports.
Relative excess is `(1 + strategy) / (1 + benchmark) - 1`.

LightGBM has one promoted window (2025H2), but a single promoted window is not
cross-window stability. XGBoost has the highest mean ICIR in this run, while
LightGBM has the better compounded portfolio outcome; both are economically
inferior to QQQ.

## Comparison with the static-universe result

| Candidate | Universe | Mean ICIR | Positive excess windows | Relative excess | Worst drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| LightGBM | Static current membership | 0.3587 | 3/4 | 65.04% | -27.34% |
| LightGBM | Window-start PIT | 0.0966 | 1/4 | -20.49% | -26.11% |
| XGBoost | Static current membership | 0.3497 | 4/4 | 70.35% | -25.63% |
| XGBoost | Window-start PIT | 0.1149 | 1/4 | -34.08% | -25.59% |

The algorithm-family difference is again small compared with the shared
validity and drawdown problem. The principal finding is not that XGBoost is
better than LightGBM; it is that the apparent static-universe alpha collapses
under the stricter membership contract.

## Engineering changes

- The canonical executor accepts `window_start_point_in_time` membership.
- The declared/effective contract embeds snapshot bytes and per-window
  membership hashes, with runtime hash verification.
- Training rows are filtered by the latest semiannual membership available on
  each row date; future OOS members cannot leak backward.
- The legacy NDX runner and canonical executor use one shared universe planner.
- Readiness and universe summaries persist the actual aligned training start by
  window rather than the requested-start placeholder.
- Static-universe contracts and execution behavior remain unchanged.

## Reproduction

```bash
uv run python scripts/run_us_feature_quality_validation.py \
  --spec configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml \
  --output-dir artifacts/evidence/lgbm_xgb_ranker_pit_robustness \
  --provider-uri <manifest-bound-us-provider>
```

The authoritative local output is:

```text
artifacts/evidence/lgbm_xgb_ranker_pit_robustness/
  us_10d_lgbm_xgb_ranker_pit_robustness/
```
