# W3 / #1282 — pinned accepted US/CN local reference

**A5 pending owner acceptance: CN reference PASS; QQQ declared replay contract PASS in follow-up PR #1293.** Main
`58a56c14c18197f700ab00b526513a571aff35be`, accepted formal cutoffs 2026-10-23.
The [receipt](w3_local_replay_2026-10-25.json) binds lockfiles, exact active model,
formal manifest/bundle, source bars/pool, evaluator, benchmark, calendar,
adjustment/execution and costs. No new runner, model or source substitution.

```powershell
uv sync --frozen --extra dev
uv run --frozen alpha research replay cn_27_v1_3
uv run --frozen alpha research replay qqq_v4_3
```

CN_27 v1.3 returned exit 0 / `exact_replay` twice with identical receipts.
The existing frozen evaluator compared report, positions, trades and attribution
at its predeclared 1e-6 numeric tolerance. Source OHLCV and pool hashes passed.
The reproduced **historical trace ends 2026-09-04**, although the accepted bundle
also carries operating observations through 2026-10-23. This is a frozen local
reference study, not a reproduction or certification of later current weights,
new OOS skill or 20 operating sessions. Its retained failed timing/bootstrap
gates and prospective status are not promoted by deterministic replication.

The initial generic QQQ CLI returned exit 2 / `data_blocked` because it imposed a
professional-only gate. That failure remains in the original receipt. Further
inspection found the existing authoritative verifier already accepts the exact
frozen Yahoo research contract; Tiingo is deliberately disabled in that contract.
[PR #1293](https://github.com/liuh886/alpha_engine/pull/1293) reuses that verifier
and records three identical successful CLI repetitions and 34 passing affected
tests. No Tiingo purchase or provider substitution is needed for this declared
research replay. Its receipt explicitly distinguishes retained frozen economic
prefix integrity from the recomputed decision path, appended economics and
cumulative continuity. It does not claim historical economics were independently
recalculated from restated current-provider prices. The implementation is pending
review/merge; the baseline command failure is not silently overwritten.

An isolated temporary copy of the accepted CN bundle with its frozen source
prices absent returned `data_blocked` with the exact missing-source reason.
Original sealed bytes were untouched. Existing replay/data-recipe/rules-gate
tests passed **25** cases, including nonzero CLI failures and economic-drift
rejection. The initially named CN-specific test file does not exist; the actual
existing suites were selected and passed before reporting validation.

Revert this derived evidence packet to roll back the audit; formal bundles,
sources, strategy weights and registries are unchanged. Owner A5 acceptance remains pending for these bounded CN and QQQ references;
no release or strategy promotion is authorized by these replay receipts.
