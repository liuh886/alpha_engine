# BYD V1.2 recovery-state evidence

## Decision

`byd_v1_2_not_supported`

- `research_only=true`
- `trade_ready=false`
- fresh historical holdout: `false`
- post-result rule or threshold change: forbidden

## Immutable data identity

- Repository snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- Snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- Canonical adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Canonical manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`
- Open policy: `entry_and_exit_open_must_be_independently_confirmed_and_not_quarantined`

The snapshot was materialized from the sealed PR #510 evidence. Model CI no longer refetches Yahoo, AkShare or any other market-data provider.

## Historical metrics

### Full history: 2012 to 2026-08-03

| Model | CAGR | Total return | Max drawdown | Calmar | Exposure | Round trips/year |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BYD V1.2 | 19.56% | 1127.35% | -53.92% | 0.3628 | 91.33% | 0.971 |
| Canonical V1.0 | 19.58% | 1130.23% | -53.69% | 0.3647 | 88.91% | 0.632 |
| Buy-and-hold | 20.04% | 1197.77% | -56.22% | 0.3564 | 100.00% | 0.000 |

### Fixed retrospective validation: 2023–2024

| Model | CAGR | Total return | Max drawdown | Calmar |
| --- | ---: | ---: | ---: | ---: |
| BYD V1.2 | 6.39% | 12.64% | -41.69% | 0.1533 |
| Canonical V1.0 | 6.10% | 12.05% | -41.39% | 0.1475 |
| Buy-and-hold | 6.19% | 12.22% | -45.82% | 0.1350 |

### Retrospective 2025 through 2026-08-03

| Model | CAGR | Total return | Max drawdown |
| --- | ---: | ---: | ---: |
| BYD V1.2 | -1.38% | -2.08% | -41.29% |
| Canonical V1.0 | 4.45% | 6.83% | -37.83% |
| Buy-and-hold | 2.23% | 3.40% | -42.94% |

## Frozen gates

| Gate | Result |
| --- | --- |
| CAGR retention >= 95% | PASS |
| Drawdown improvement >= 3 percentage points | **FAIL** |
| Calmar >= buy-and-hold | PASS |
| 2023–2024 return positive | PASS |
| 2023–2024 drawdown improvement >= 3 points | PASS |
| 40 bps total return positive | PASS |
| <= 2 round trips/year | PASS |
| Largest defense episode <= 50% | PASS — 18.87% |
| Not dominated by canonical V1.0 | **FAIL** |

## Conditional ten-session IC

All values below are oriented so a positive value indicates the pre-registered economic direction.

| Factor | All | Bull | Bear | Sideways | High vol | Low vol |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| reverse `drawdown_252` | 0.1053 | 0.0492 | 0.2248 | 0.0999 | 0.1573 | 0.0904 |
| reverse `mom_120` | 0.0633 | 0.0456 | 0.0956 | 0.0108 | 0.1668 | 0.0372 |
| `distance_from_low_20` | 0.0824 | 0.0609 | 0.0796 | 0.1828 | 0.0188 | 0.1048 |
| `momentum_accel_20_60` | 0.0611 | 0.0928 | 0.0051 | -0.0141 | 0.1116 | 0.0210 |
| `open_return_autocorr_20` | 0.0692 | 0.0122 | 0.0903 | 0.1558 | 0.0506 | 0.0917 |

## Interpretation

The factor map contains real conditional information, but the frozen all-in-one V1.2 state machine did not convert it into a better portfolio rule. In particular, momentum acceleration was incorrectly required across states where its conditional IC is near zero or negative.

The next experiment may preserve canonical V1.0 as the base model and evaluate one pre-registered state-conditioned recovery overlay. It must be a new experiment; V1.2 may not be repaired retrospectively.

## Reproducible artifact

- GitHub Actions run: `30898006635`
- Artifact ID: `8887864758`
- Artifact ZIP SHA-256: `379fc3add6b1ec1cc825977ca423a47d230eb5d94402ff08201ed693a6c9d44c`

The artifact contains factor clusters, full conditional 5/10/20-day IC, daily positions and returns, trade changes, defense episodes, canonical V1.0 comparison, and the initial prospective ledger row.
