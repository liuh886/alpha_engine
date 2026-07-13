# AlphaEngine post-handoff completion record

**Date:** 2026-07-13  
**Repository:** `liuh886/alpha_engine`

## Completed closure

- PR #150 was completed, cleaned, validated, marked ready, and squash-merged.
- Merge commit: `5e5fa5d1bc43ee55a79a87943b2a9ab188d4374f`.
- Issue #148 was closed by the merge.
- All one-time OOS migration workflows and patch scripts were removed before merge.
- The final #150 head passed backend and frontend CI, Ruff, mypy, Fast PR pytest, and the CN real-pyqlib integration test.

## Current-contract real-market evidence

The CN and US pipelines were rerun from the post-#150 main contract through execution-only PR #153 and workflow run `29225709306`.

Durable evidence is preserved at:

```text
docs/evidence/post-150-current-2026-07-13/
```

The package records:

- source main commit and workflow provenance;
- GitHub artifact digests;
- exact source-report SHA-256 values;
- input contracts and exit codes;
- acceptance checks;
- complete and excluded OOS windows;
- canonical-expression counts and leading diagnostic candidates;
- promotion and trade-readiness boundaries;
- the CN refresh-quality caveat and failed-symbol list.

### Results

| Market | Update / provider / pipeline | Acceptance | Expressions / factor IDs | Rebalance dates | Status |
|---|---|---|---:|---:|---|
| CN | `1 / 0 / 0` | `10 pass / 1 warn / 0 fail` | `23 / 47` | `46` | diagnostics completed |
| US | `0 / 0 / 0` | `10 pass / 1 warn / 0 fail` | `9 / 24` | `48` | diagnostics completed |

Both markets used the four complete windows `2024H1`, `2024H2`, `2025H1`, and `2025H2`. The partial `2026H1` window is explicitly recorded and excluded by `complete_windows_only`; it does not count toward `min_windows`.

Both outputs remain:

```text
diagnostic_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

## CN declared-end closure

The earlier CN current-snapshot caveat was resolved through Issue #156 and PRs #158 and #160.

PR #158 separated reproducible historical refreshes from current-snapshot freshness checks. PR #160 then corrected the remaining provider-boundary mismatch: AlphaEngine treats a declared `end` as inclusive, whereas yfinance treats its provider `end` as exclusive.

The final production implementation is commit:

```text
10a3bb3d61e57b74b37c6deecfbdcad9769e6427
```

Post-merge verification was performed through execution-only PR #161 and workflow run `29261434173`. The temporary workflow was not merged.

Durable closure evidence is preserved at:

```text
docs/evidence/post-160-cn-verification-2026-07-13/
```

### Final CN verification

| Item | Result |
|---|---|
| Fixed interval | `2021-01-01` through inclusive `2026-06-18` |
| Configured input | 224 symbols including `000300` |
| Provider attempts | 171 succeeded / 53 failed and visibly excluded |
| Retained terminal coverage | all 171 instruments end on `2026-06-18` |
| Update / provider / pipeline | `2 / 0 / 0` |
| Acceptance | `10 pass / 1 warn / 0 fail` |
| Canonical expressions / factor IDs | `23 / 47` |
| Sampled rebalance dates | 46 |
| Final workflow assertion | passed |

The quality report records:

- `freshness_scope.mode=declared_interval`;
- effective calendar `2021-01-04` through `2026-06-18`;
- 1,321 sessions;
- zero stale instruments;
- zero missing, stale, or unparsable retained CSVs.

The 53 provider failures remain auditable and were not replaced with stale cache bytes, synthetic data, zero fill, or silent imputation. The accepted retained universe remains well above the CN minimum coverage requirement.

## Final project state

The research-data and reproducible-diagnostics milestone is complete:

- Issue #124 real-market evidence is preserved.
- Canonical factor identity and alias separation are active.
- OOS-window and forward-label boundaries are explicit and enforced.
- Historical declared-end refresh and current-snapshot freshness are separately classified.
- Provider failures and retained-universe identity are auditable.
- CN and US canonical pipelines pass real-market acceptance.
- Issue #156 is closed by successful post-merge verification.
- No temporary execution workflow is merged into `main`.

The current outputs intentionally remain:

```text
diagnostic_only=true
research_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

This is the completed research boundary. A model promotion, production signal, or trading-readiness decision would be a new reviewed research milestone rather than unfinished work from the present milestone.

## Completion checklist

- [x] Issue #124 historical real-market evidence remains immutable.
- [x] Canonical factor identity is active.
- [x] PR #150 production integration is complete.
- [x] One-time migration infrastructure was removed.
- [x] CN/US evidence was rerun under the current contract.
- [x] Current-contract evidence was versioned separately from Issue #124.
- [x] Canonical-expression review was completed.
- [x] Declared historical intervals are propagated through providers.
- [x] yfinance inclusive/exclusive end semantics are reconciled.
- [x] Post-merge real CN verification passed.
- [x] Issue #156 closure evidence is durably preserved.
