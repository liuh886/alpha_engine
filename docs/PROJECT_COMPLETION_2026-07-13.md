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

## CN data-quality boundary

The CN update command returned `1` because the current-day snapshot quality check found one stale retained instrument and a large volume discrepancy for `000002`. Provider construction and the fixed research pipeline returned `0`; the declared interval through `2026-06-18` passed acceptance.

This distinction is preserved rather than hidden. Issue #156 owns the required correction to bind historical research refreshes to the declared interval while keeping current-day freshness fail-closed.

## Follow-up responsibility gates

- Issue #155: canonical-expression factor review. This is a diagnostic review gate and does not authorize factor-library, orientation, model, promotion, or trading changes.
- Issue #156: declared-end refresh and CN freshness-classification hardening.

These are explicit next-stage work items, not omissions from the completed #148/#150 handoff.

## Completion checklist

- [x] Issue #124 historical real-market evidence remains immutable.
- [x] Canonical factor identity is active.
- [x] PR #150 production integration is complete.
- [x] One-time migration infrastructure was removed.
- [x] PR #150 final CI passed and the PR was merged.
- [x] Issue #148 was closed.
- [x] CN/US evidence was rerun under the new contract.
- [x] Current-contract evidence was versioned separately from Issue #124.
- [x] An independent factor-review issue was created.
- [x] The newly exposed CN refresh-quality problem was assigned to a separate issue.
