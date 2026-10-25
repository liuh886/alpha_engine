# W3 / #1282 — pinned accepted US/CN local reference

**A5 BLOCKED: CN reference PASS, US reference BLOCKED.** Main
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

QQQ v4.3 returned exit 2 / `data_blocked`: the exact-cutoff recipe manifest has
`professional_source_ready=false`. Its existing contract requires a professional
governed ETF product and `TIINGO_API_TOKEN`; a cached research-grade product does
not satisfy it. No secret value is read into this receipt. Configure the existing
provider securely and rebuild only the exact-cutoff product, then rerun the same
accepted command. Do not replace it with a retired US model, relax the source
gate or edit accepted economics. This blocker belongs to the existing QQQ
reference/data recipe, not a reason to duplicate #324/#325/#826.

An isolated temporary copy of the accepted CN bundle with its frozen source
prices absent returned `data_blocked` with the exact missing-source reason.
Original sealed bytes were untouched. Existing replay/data-recipe/rules-gate
tests passed **25** cases, including nonzero CLI failures and economic-drift
rejection. The initially named CN-specific test file does not exist; the actual
existing suites were selected and passed before reporting validation.

Revert this derived evidence packet to roll back the audit; formal bundles,
sources, strategy weights and registries are unchanged. A5 cannot pass until
the accepted US reference is independently reproduced as well. Owner review
of this bounded CN reference and US blocker remains required.
