# BYD V1.3 state-conditioned recovery overlay evidence

## Decision

`byd_v1_3_not_supported`

- `research_only=true`
- `trade_ready=false`
- fresh historical holdout: `false`
- post-result threshold or rule change: forbidden

V1.3 retained canonical V1.0 unchanged and tested one frozen event overlay. The overlay improved full-history drawdown and Calmar, but its positive benefit was too concentrated in the pre-2023 development period to pass the pre-registered temporal-diversification gate.

## Immutable data identity

- Snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- Snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- Canonical adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Canonical manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`
- Open policy: `entry_and_exit_open_must_be_independently_confirmed_and_not_quarantined`

Model CI was fully offline and used no provider refetch or row substitution.

## Full-history comparison

| Model | CAGR | Total return | Max drawdown | Calmar | Exposure | Round trips/year |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BYD V1.3 | 19.47% | 1114.48% | -51.62% | 0.3772 | 90.61% | 1.042 |
| Canonical V1.0 | 19.58% | 1130.23% | -53.69% | 0.3647 | 88.91% | 0.632 |
| Buy-and-hold | 20.04% | 1197.77% | -56.22% | 0.3564 | 100.00% | 0.000 |

Relative to V1.0, V1.3 improved maximum drawdown by approximately 2.07 percentage points and Calmar by 0.0125, while reducing CAGR by approximately 0.11 percentage points.

## Retrospective windows

| Window | Model | Total return | Max drawdown | Calmar |
| --- | --- | ---: | ---: | ---: |
| 2023–2024 | V1.3 | 12.35% | -41.61% | 0.1502 |
| 2023–2024 | V1.0 | 12.05% | -41.39% | 0.1475 |
| 2025–2026-08-03 | V1.3 | 6.67% | -37.92% | 0.1147 |
| 2025–2026-08-03 | V1.0 | 6.83% | -37.83% | 0.1178 |

At 40 bps per unit position change, V1.3 retained a full-history Calmar of 0.3627 versus 0.3562 for V1.0.

## Frozen gates

| Gate | Result |
| --- | --- |
| CAGR shortfall <= 0.25 percentage points | PASS |
| Drawdown worsening <= 0.50 points | PASS |
| Calmar strictly above V1.0 | PASS |
| 2023–2024 total return >= V1.0 | PASS |
| 2023–2024 drawdown within 1 point | PASS |
| 2025+ total-return shortfall <= 1 point | PASS |
| 40 bps Calmar >= V1.0 at 40 bps | PASS |
| Incremental turnover <= 0.50 round trips/year | PASS — 0.4097 |
| At least 10 completed events | PASS — 25 |
| Largest positive episode <= 50% | PASS — 15.72% |
| One period <= 60% of positive benefit | **FAIL — 89.53%** |

## Event evidence

Twenty-five completed events occurred:

| Period | Events | Positive events | Sum of positive benefit | Share of positive benefit |
| --- | ---: | ---: | ---: | ---: |
| Development through 2022 | 20 | 10 | 16.75% | 89.53% |
| Fixed validation 2023–2024 | 3 | 2 | 1.12% | 5.99% |
| Retrospective 2025+ | 2 | 1 | 0.84% | 4.48% |

Branch attribution:

| Branch | Events | Positive events | Mean relative benefit |
| --- | ---: | ---: | ---: |
| Bear/sideways low volatility | 20 | 10 | -0.20% |
| Bull high volatility | 5 | 3 | +0.87% |

The bull/high-volatility branch had only five events, all in the development period. Narrowing the model to that branch after seeing these outcomes would be post-selection and is therefore prohibited.

## Interpretation

V1.3 shows that recovery overlays can improve the historical drawdown/return trade-off, but the evidence does not generalize across time. The correct next step is not V1.4 threshold optimization on the same observed history. Canonical V1.0 remains the retained baseline, while the frozen recovery conditions may be recorded prospectively as a shadow event ledger.

## Reproducible artifact

- GitHub Actions run: `30899112414`
- Artifact ID: `8888309761`
- Artifact ZIP SHA-256: `53cd4155a744d97a1bbc87f59886230f357e36d6c841dfae673e18e6ac1cebcc`

The artifact contains exact base/overlay positions, the 25-event ledger, trades, daily returns, 20/40 bps comparisons, concentration statistics and the initial prospective row.
