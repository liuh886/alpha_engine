# BYD V1.2 recovery/reversal state model

This experiment is the first BYD model stage that is required to consume the sealed canonical v1 data identity directly.

## Hard data dependency

- Schema: `byd_canonical_adjusted_ohlcv_v1`
- Adjusted SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- Cutoff: `2026-08-03`
- Cross-provider stitching: forbidden
- Quarantined entry or exit opens: forbidden

The workflow first runs the merged canonical build, factor-event finalization, independent raw-source audit and manifest sealing pipeline. The model starts only when the rebuilt adjusted data and sealed manifest match the exact frozen identities above; otherwise it fails closed.

## Frozen model family

Only one interpretable state machine is evaluated. It uses:

- `drawdown_252` and `mom_120` for the long-horizon state;
- `distance_from_low_20` for recovery confirmation;
- `momentum_accel_20_60` for momentum transition;
- `open_return_autocorr_20` for open-market structure.

The model switches only between 75% and 100% BYD. Rules, costs and gates are frozen in `configs/research_paradigms/byd_v1_2_recovery_state.yaml` before the historical result is generated.

## Validation boundary

All history through 2026-08-03 has already been observed. Historical output is explanatory evidence only. The first prospective record starts on 2026-08-04; no result from the frozen history can make the model trade-ready.
