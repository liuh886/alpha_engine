# E5 phase-one acceptance

Related architecture and original evidence: PR #1380. E5's independent feature
branch adds observation to the existing canonical engine, not another simulator.
See the [implementation contract](../../research/e5_portfolio_ledger_2026-11-07.md)
and [actual research report](../../research/e5_us73_shortlist_results_2026-11-07.md).

All 4 approved configurations × 8 folds pass original E4 daily and aggregate
parity. All 64 original/delayed ledgers pass independent offline arithmetic
checks. Raw prices, complete scores and per-asset ledgers stay in a private
235-member archive; only receipts and derived summaries are published here.

`acceptance.json` binds original E4/v6 identities, evaluator code, tolerances,
actual paired results and package hashes. `delivery.json` records the four
core Drive filesystem files plus the exact-code provenance capsule and SHA256 readback. Google Drive Desktop handles sync;
no new remote upload-completion, ACL, licence, PIT or actual-fill certification
is inferred from local readback.

The archive was independently read/extracted offline into a fresh directory;
all 32 result inventories are readable and a fresh canonical replay reproduces
both execution-mode summaries from the restored scores, without any fit.

`code-provenance.json` binds a separate private exact-source capsule (393,245
bytes), including the pinned E4 driver, evaluator files, lockfile and both
reconstruction-script byte versions. The initial source snapshot and first two
score slices preceded the first commit; their exact earlier script bytes were
reconstructed and SHA256 matched to the existing receipts. The later committed
worker adds boundary validation and preserves the same feature/model math.
Neither result receipts nor the sealed main archive were rewritten. Delivery
now consists of five files, including this necessary provenance supplement.

Decision: **E5_LEDGER_PARITY_ACCEPTED_RESEARCH_PROVISIONAL**. No model promotion.
The original 288 E4 records, archive, pointer and comparison remain unchanged.
