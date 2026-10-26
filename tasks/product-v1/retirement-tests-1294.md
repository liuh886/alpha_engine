# #1294 — complete-suite CN x1.2 retirement expectations

Plan: retain historical exact package/promotion/failed-gate checks; replace
obsolete active-publication expectations with actual retirement negative paths;
verify source/registry/catalog immutability and rerun the affected existing shard.

Observed baseline: all 500 backend test files inspected via existing CI four-bin
partitioning; 3934 PASS / 2 FAIL / 8 SKIP. Both failures expected retired CN x1.2
to materialize or appear active, contrary to current AGENTS/registry. The initial
single-process quality command failed earlier at collection MemoryError; separate
ten-test reproduction passed. These original failures remain retained.

Implementation: exact historical package remains tested; both catalog-update
modes reject retirement, retain an exact failed-attempt source package, create
no active publication and alter no canonical files. Catalogs match the exact
four-strategy registry. No runtime/model/registry/evidence changes or new skips.

Validation PASS: 5 targeted tests; affected frozen shard rerun 931 PASS / 6
approved skips. Combined with unchanged original shards 0–2, all 500 files are
covered once: 3938 PASS / 8 approved skips / 0 FAIL. Ruff/diff PASS. The original
single-process quality FAIL remains in evidence, not relabeled as green; this
is not a new pinned-candidate quality certificate or a test of separate #1293.
GitHub GraphQL returned EOF during issue creation/listing;
REST verified no duplicate and created #1294. No network failure was called PASS.
