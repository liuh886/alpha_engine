# Post-#150 current-contract real-market evidence

This package preserves the CN and US rerun performed on 2026-07-13 after PR #150 made incomplete OOS-window treatment an explicit versioned contract.

## Provenance

- source main commit: `5e5fa5d1bc43ee55a79a87943b2a9ab188d4374f`;
- execution-only PR: #153;
- workflow run: `29225709306`;
- CN artifact digest: `sha256:a07bd75f4ec226dc6dafdec9e7126988f8c982546b38712b42124463924e3dd2`;
- US artifact digest: `sha256:82a6db3484ead846dc4260962468a72e2c4ff77e75365e5815e894343f8b06b6`;
- canonical `test_end`: `2026-06-18`;
- paradigm schema: `1.1`;
- diagnostics schema: `1.3`;
- partial-window policy: `complete_windows_only`;
- `min_windows` counts complete windows only.

The historical Issue #124 evidence is not overwritten.

## Results

| Market | Update / provider / pipeline | Acceptance | Canonical expressions / IDs | Rebalance dates | Included OOS windows | Promotion / trade |
|---|---|---|---:|---:|---|---|
| CN | `1 / 0 / 0` | `10 pass / 1 warn / 0 fail` | `23 / 47` | `46` | `2024H1, 2024H2, 2025H1, 2025H2` | `false / false` |
| US | `0 / 0 / 0` | `10 pass / 1 warn / 0 fail` | `9 / 24` | `48` | `2024H1, 2024H2, 2025H1, 2025H2` | `false / false` |

Both markets accepted the real provider and completed factor diagnostics. Both remain diagnostic-only: `promotion_eligible=false`, `promotion_evaluated=false`, and `trade_ready=false`.

## Window-policy verification

Both markets used four complete windows: `2024H1`, `2024H2`, `2025H1`, and `2025H2`. `2026H1` is present in evidence as an excluded partial final window with `effective_test_end=2026-06-18`, `natural_test_end=2026-06-30`, and `counts_toward_min_windows=false`. `2026H2` is excluded because it had not started by the requested end date.

No sampled 10-session label crosses the effective window end or declared `test_end`.

## CN refresh caveat

The CN update command returned `1`, while provider construction and fixed-contract research both returned `0`.

- configured input: `224` symbols including benchmark;
- successfully refreshed: `197`;
- failed and fail-closed: `27`;
- acceptance: `10 pass / 1 warn / 0 fail`;
- quality warnings: `market=cn: 1 stale instruments (end < calendar latest); [000002] volume difference too high: 99.00%`.

The update failure is a current-day snapshot publication issue, not a failure of the declared research interval. The retained provider covers the fixed interval through `2026-06-18`, acceptance passed, and factor diagnostics completed. This does not imply promotion readiness.

## Interpretation boundary

These outputs are factor diagnostics, not a deployable model or trading signal. Factor-library changes, orientation changes, combination research, model fitting, promotion, or trade readiness require separate reviewed work.

See `evidence_index.json` for compact machine-readable market summaries, factor rankings, window evidence, failed-symbol lists, artifact provenance, and exact source-file hashes.
