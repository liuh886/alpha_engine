# Post-#160 declared-end CN verification

**Closure date:** 2026-07-13  
**Production source:** `10a3bb3d61e57b74b37c6deecfbdcad9769e6427`  
**Merged implementation:** PR #160  
**Tracking issue:** #156  
**Execution-only verification:** PR #161, workflow run `29261434173`

## Verdict

The declared-end CN chain passed end to end after PR #160:

| Stage | Exit / result |
|---|---|
| Historical refresh | `2` — completed with auditable missing-symbol warnings |
| CN market-provider build | `0` |
| Canonical CN research pipeline | `0` |
| Real-market acceptance | `10 pass / 1 warn / 0 fail` |
| Factor diagnostics | completed, schema `1.3` |
| Final workflow assertion | passed |

The successful workflow artifact was `8284264097`, digest
`sha256:0a79235b05f8ea2e2425671a6446e589336ff730f72095efff59620336a6c79f`.

## Fixed contract

- Market: CN
- Universe: `configs/research_universes/cn_curated_equities_v1.yaml`
- Configured input: 224 symbols including benchmark
- Benchmark: `000300`
- Declared interval: `2021-01-01` through inclusive `2026-06-18`
- Research spec: `configs/research_paradigms/cn_10d_csi300_baseline.yaml`
- Cadence / horizon: 10 sessions / 10 sessions
- Partial-window policy: `complete_windows_only`

## Data verdict

The provider router successfully retained **171** instruments and reported **53**
provider failures. Every failed symbol remains listed in `evidence_index.json`.
No failed symbol was recovered from stale cache, zero-filled, synthetically
substituted, or silently imputed.

For the retained set:

- effective calendar: `2021-01-04` to `2026-06-18`, 1,321 sessions;
- instrument terminal-date range: `2026-06-18` to `2026-06-18`;
- CSV terminal-date range: `2026-06-18` to `2026-06-18`;
- stale instruments: 0;
- missing CSVs: 0;
- CSV parse failures: 0;
- stale CSVs: 0.

This confirms that AlphaEngine's inclusive research boundary is now preserved
through yfinance's exclusive provider boundary without weakening the stale-data
gate.

## Research verdict

- accepted: true;
- canonical expressions / configured factor IDs: `23 / 47`;
- sampled rebalance dates: 46;
- complete OOS windows: 4;
- acceptance and factor-diagnostic stages: passed.

The result intentionally remains:

```text
diagnostic_only=true
research_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

This is the expected research boundary, not an incomplete implementation.
Promotion or trading authorization requires a separate reviewed research change.

## Evidence integrity

`evidence_index.json` preserves the exact contract, result counts, failed-symbol
list, provider identity, workflow provenance, and SHA-256 values for every raw
artifact in the successful Actions package. The temporary workflow in PR #161
was execution-only and was not merged into `main`.
