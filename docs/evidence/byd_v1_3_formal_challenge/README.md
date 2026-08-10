# BYD v1.3 formal challenge evidence

Decision: **`byd_v1_3_not_supported`**  
Champion retained: **BYD v1.2 (`byd_v1_2_convex_momentum_budget_v1`)**  
Evidence cutoff: **2026-08-03**  
Research only: **true**  
Trade ready: **false**

## Frozen candidate

The formal challenge tested exactly the V1.3 candidate frozen after Issue #716:

1. 20-session minimum hold on inherited V1.2 base risk-target transitions;
2. 55% BYD / 45% 515180 while the held target is defensive and the governed market state is `bear`;
3. the existing V1.2 expansion state with 15% maximum financed increment and convex power 2.0.

No parameter, state definition, execution rule, evaluation window, cost assumption or gate changed after the formal result was observed.

## Champion identity

The challenge does not reconstruct an approximate V1.2 baseline. It directly reuses the maintained V1.2 implementation and verifies the rebuilt 2026-08-03 path against the durable Research Loop baseline receipt:

- bundle ID: `a36cee1bab0069369b4a994158a96998829846eb7cf7997cef86b3e447cf41a1`;
- manifest SHA-256: `e727056e6016e217747703b4f01c7e944edb4300b624ee0bec6f474beb787dd1`;
- CAGR: 35.8435%;
- Sharpe: 0.9266;
- max drawdown: -49.20%;
- total return: +607.04%.

All four reproduced metrics matched the frozen receipt exactly in the authoritative CI run.

The repository's rolling formal package has since advanced through later evidence dates; it is used only to confirm that V1.2 remains the currently published BYD champion. It is not mixed into this frozen historical comparison.

## Primary result — 20 bps / 6% financing

| Window | Metric | V1.2 | V1.3 | Read-through |
| --- | --- | ---: | ---: | --- |
| Full overlap | CAGR | 35.84% | 33.97% | **FAIL** — -1.87pp |
| Full overlap | Sharpe | 0.9266 | 0.9060 | **FAIL** |
| Full overlap | Max drawdown | -49.20% | -46.23% | PASS — +2.97pp |
| Full overlap | Calmar | 0.7285 | 0.7348 | PASS |
| 2023–2024 | CAGR | 8.16% | 9.68% | PASS |
| 2025+ | CAGR | 6.16% | 3.18% | **FAIL** |
| Full overlap | Round trips/year | 1.31 | 1.89 | PASS |

The candidate reduces volatility and drawdown, but it gives back too much return. Its full-period total return falls from +607.04% to +547.01%.

## Stress result — 40 bps / 10% financing

| Metric | V1.2 | V1.3 | Result |
| --- | ---: | ---: | --- |
| Full CAGR | 35.12% | 32.94% | **FAIL** — -2.18pp |
| Full Max drawdown | -49.79% | -47.05% | PASS — +2.74pp |
| Full Calmar | 0.7053 | 0.7000 | **FAIL** |

The risk reduction survives stress costs, but the return and Calmar requirements do not.

## Temporal attribution

Relative terminal wealth versus V1.2:

| Period | Relative wealth | Positive-benefit share |
| --- | ---: | ---: |
| Development through 2022 | -7.00% | 0% |
| 2023–2024 | +2.73% | **100%** |
| 2025+ | -4.22% | 0% |

The frozen concentration cap is 60%. Because all positive relative benefit comes from a single period, the candidate fails the temporal-diversification gate decisively.

## Failed gates

- `primary_full_cagr`
- `primary_full_sharpe`
- `retrospective_2025_plus_cagr`
- `stress_full_cagr`
- `stress_full_calmar`
- `positive_period_concentration`

Five gates passed: primary Calmar, primary drawdown improvement, fixed-validation CAGR, turnover cap, and stress drawdown improvement.

## Reproduction

Authoritative workflow run: `31367573154`  
Artifact ID: `9054791084`  
Artifact ZIP SHA-256: `9a6db5312f573882a9b20491114b20205280d58657b818e3e7f205b11a95af9a`

The workflow artifact contains the exact V1.2 and V1.3 daily traces. Their SHA-256 identities are retained in `manifest.json`; the compact decision, comparison and attribution evidence is committed here. Backend CI rebuilds the daily traces from immutable inputs and byte-compares the durable evidence files, so the negative decision remains reproducible without committing duplicate large daily ledgers.

## Decision

Do not promote this candidate. BYD v1.2 remains the formal champion. The result should be retained as research memory; any future successor must be a separately frozen hypothesis rather than a post-result repair of these three parameters.
