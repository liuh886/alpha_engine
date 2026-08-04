# BYD V1.3 state-conditioned recovery overlay

V1.3 preserved canonical V1.0 unchanged and tested one pre-registered event overlay. The experiment is complete and **not supported**.

## Immutable data

- Snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- Snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- Adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`

Model CI was offline and did not refetch or substitute a provider.

## Base model

Canonical V1.0 remained exactly:

- 75% permanent BYD core;
- 100% target when close is above SMA120 and 20-session momentum is positive;
- 75% target when close is below SMA120 and 60-session momentum is negative;
- execution at the next independently confirmed eligible open.

## Overlay

The overlay could only lift a 75% V1.0 target to 100%.

- Bear/sideways, low volatility: long drawdown, recovery from the 20-day low and positive open-return autocorrelation.
- Bull, high volatility: drawdown, recovery from the 20-day low and positive 20/60-day momentum acceleration.

A false-to-true event lasted exactly ten eligible open intervals, followed by a ten-eligible-open same-branch cooldown. Quarantined opens advanced neither clock.

## Decision

`byd_v1_3_not_supported`

V1.3 produced 25 completed overlay events. It improved full-history maximum drawdown from -53.69% to -51.62% and Calmar from 0.3647 to 0.3772, while CAGR declined from 19.58% to 19.47%.

Ten of eleven frozen gates passed. The failure was temporal concentration: 89.53% of all positive overlay benefit came from the pre-2023 development period, above the frozen 60% cap. Only three events occurred in 2023–2024 and two after 2024; the 2025+ overlay result was slightly below canonical V1.0.

The positive historical result is therefore not sufficiently distributed across time. The model remains `research_only=true`, `trade_ready=false`, and cannot be repaired by selecting only the historically better branch or changing the concentration gate.

## Research implication

The historical work has reached a governance boundary. Further narrowing on the same observed events would be post-selection:

- the bull/high-volatility branch had a positive mean outcome but only five events, all before 2022;
- the bear/sideways low-volatility branch had more events but a slightly negative mean incremental outcome;
- choosing between them now would use the evaluation result to redefine the model.

Canonical V1.0 remains the retained baseline. The recovery conditions may continue only as a prospective shadow event ledger on newly versioned daily data. No V1.4 historical threshold search is justified from the same frozen sample.

## Evidence

See `docs/evidence/byd_v1_3_recovery_overlay/README.md` and the full GitHub Actions artifact for daily positions, event attribution, costs and concentration statistics.
