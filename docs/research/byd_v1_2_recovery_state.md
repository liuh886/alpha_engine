# BYD V1.2 recovery/reversal state model

BYD V1.2 is the first model stage that consumes the sealed canonical v1 data identity as an immutable repository asset. The experiment is complete and **not supported**.

## Hard data dependency

- Snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- Snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- Schema: `byd_canonical_adjusted_ohlcv_v1`
- Adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`
- Cross-provider stitching: forbidden
- Quarantined entry or exit opens: forbidden

Model CI is offline with respect to market data. It verifies the archive SHA, extracts the snapshot, then verifies the internal adjusted-series and manifest identities. A supplier refetch cannot alter this experiment.

This stronger rule was added after a live rerun showed that Yahoo had retrospectively changed `Adj Close` while the unadjusted raw-price SHA remained unchanged. Provider/date/code pinning alone was therefore insufficient for reproducibility.

## Frozen model family

Only one interpretable state machine was evaluated. It used:

- `drawdown_252` and `mom_120` for the long-horizon state;
- `distance_from_low_20` for recovery confirmation;
- `momentum_accel_20_60` for momentum transition;
- `open_return_autocorr_20` for open-market structure.

The model switched only between 75% and 100% BYD. Rules, costs and gates were frozen in `configs/research_paradigms/byd_v1_2_recovery_state.yaml` before the historical result.

## Decision

`byd_v1_2_not_supported`

Full history, 2012 through 2026-08-03:

| Model | CAGR | Total return | Max drawdown | Calmar | Exposure | Round trips/year |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BYD V1.2 | 19.56% | 1127.35% | -53.92% | 0.3628 | 91.33% | 0.971 |
| Canonical V1.0 | 19.58% | 1130.23% | -53.69% | 0.3647 | 88.91% | 0.632 |
| BYD buy-and-hold | 20.04% | 1197.77% | -56.22% | 0.3564 | 100.00% | 0.000 |

V1.2 failed two pre-registered gates:

- maximum-drawdown improvement versus buy-and-hold was about 2.31 percentage points, below the required 3 points;
- the model was dominated by canonical V1.0 on return, drawdown and Calmar.

The 2023–2024 retrospective window was slightly better than V1.0, but 2025 through 2026-08-03 returned -2.08%, versus +6.83% for V1.0. The negative decision is retained without threshold repair.

## Factor interpretation

The conditional IC evidence remains useful even though the state machine failed:

- long-horizon reversal is strongest in bear and high-volatility states;
- `distance_from_low_20` is strongest in sideways and low-volatility states;
- `momentum_accel_20_60` is useful mainly in bull/high-volatility states and is weak in bear/sideways states;
- `open_return_autocorr_20` is strongest in sideways, bear and low-volatility states.

The next valid hypothesis is therefore not a replacement for V1.0. It is a tightly bounded, state-conditioned recovery overlay on top of V1.0, with momentum acceleration excluded from states where its conditional IC is weak.

## Validation boundary

All history through 2026-08-03 has already been observed. Historical output is explanatory evidence only. V1.2 is rejected, remains `research_only=true`, and is not eligible for prospective promotion. Any successor requires a new contract frozen before its result is calculated.
