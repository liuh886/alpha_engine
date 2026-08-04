# BYD V1.3 state-conditioned recovery overlay

V1.3 preserves canonical V1.0 unchanged and tests one pre-registered event overlay. It is not a parameter scan or a replacement state machine.

## Immutable data

- Snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- Snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- Adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`

Model CI is offline and may not refetch or substitute a provider.

## Base model

Canonical V1.0 remains exactly:

- 75% permanent BYD core;
- 100% target when close is above SMA120 and 20-session momentum is positive;
- 75% target when close is below SMA120 and 60-session momentum is negative;
- execution at the next independently confirmed eligible open.

## Overlay

The overlay may only lift a 75% V1.0 target to 100%.

- Bear/sideways, low volatility: long drawdown, recovery from the 20-day low and positive open-return autocorrelation.
- Bull, high volatility: drawdown, recovery from the 20-day low and positive 20/60-day momentum acceleration.

A false-to-true event lasts exactly ten eligible open intervals, followed by a ten-eligible-open same-branch cooldown. Quarantined opens do not advance either clock.

## Governance

The full contract and support gates were frozen in Issue #516 and `configs/research_paradigms/byd_v1_3_recovery_overlay.yaml` before any V1.3 result. All history through 2026-08-03 is already observed; historical evidence cannot make the model trade-ready.
