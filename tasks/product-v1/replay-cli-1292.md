# #1292 — accepted QQQ replay CLI contract alignment

Plan: reproduce the generic CLI/source-contract mismatch; reuse the existing
authoritative QQQ verifier; remove duplicated evaluation/validation; verify
hash-bound source selection, unchanged model/economics and honest source flags;
run targeted suites and repeated actual replay before a scoped review PR.

Observed: active accepted QQQ lineage uses the frozen Yahoo research contract,
professional_source_ready=false. The generic CLI alone required professional
readiness/Tiingo. Existing verify_rules_formal_replay.py qqq already replays the
accepted reference successfully with strict source, decision, frozen-economic,
appended-economic and continuity checks. No new source policy is needed.

Implementation: reuse that verifier; bind its source ETF manifest via the
verified recipe manifest; reject missing/malformed bindings and source hash drift.
Preserve frozen historical economics rather than claim they were recomputed
from current-provider adjusted prices. No strategy/pool/cost changes or promotion.

Validation: 34 replay/data-recipe/rules-gate tests PASS using isolated
worktree code with the original governed data root; Ruff/diff PASS. Two actual
aligned CLI runs returned identical exact_replay receipts, professional flag
false. A subsequent run under concurrent full-suite load hit NumPy
ArrayMemoryError (536 KiB allocation); failure retained. After baseline shards
exited, the final isolated CLI succeeded and matched both earlier receipts:
three successful identical replays, plus the separately retained resource failure.

The code lives in a separate sparse worktree so ongoing baseline quality shards
are not changed. Initial no-checkout index was initialized only in this new,
agent-created worktree before edits, then verified clean. The baseline full
single-process suite failed collection MemoryError; 3/4 existing CI-style shards
passed independently; the fourth found two stale CN x1.2-active assertions.
This PR does not claim those baseline tests as a test of its
new source implementation or certify v1/privacy/20-session readiness.
