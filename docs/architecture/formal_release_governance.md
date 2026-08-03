# Formal release governance

Alpha Engine publishes a static, research-only artifact studio. The release system deliberately separates repository research evidence from the smaller set of named formal backtests exposed in the frontend selector.

## Two publication catalogs

`data/research/catalog.json` governs repository-backed research metadata and retained run evidence. It may contain active and superseded named models when their historical evidence remains useful. For example, US x1.0 remains in the repository bundle as immutable historical evidence even though US x1.1 supersedes it as the active US baseline.

`data/research/formal_backtests/catalog.json` is the stricter frontend allow-list. It currently exposes exactly:

1. QQQ Rotation v4.2;
2. US x1.1;
3. CN x1.0.

US x1.0 is therefore allowed in `bundle/data/models.json` but must not appear in the formal model selector. Exploratory experiments, candidate grids, rejected candidates and shadow strategies are excluded from the formal catalog.

Both catalogs retain `research_only=true` and `trade_ready=false`. The browser does not train models, generate signals or write results back to the repository.

## Pages publication impact

Every push to `main` runs the lightweight publication-impact detector before any Pages build. The detector resolves the current dependency graph from the repository catalog and deploys only when a changed path can alter the public artifact.

Direct publication dependencies include:

- `qlib-dashboard/**`;
- `data/research/formal_backtests/**`;
- the repository catalog;
- model contracts listed by that catalog;
- run directories listed by that catalog;
- result reports referenced by published model contracts;
- the static exporters, bundle schema/runtime, release verifier and Pages workflows.

Unreferenced experiments, candidate cards and ordinary unpublished research notes do not trigger the expensive build, deployment, Chromium installation or live browser suite.

The detector fails closed. An unreadable catalog, missing published source, unsupported report declaration or unavailable commit range produces `deploy=true`. Every decision is retained as a `pages-impact-decision` workflow artifact. A deployed `deployment.json` also records the impact reason and matched publication paths.

The independent `workflow_run` observer is the sole writer of the rolling production receipt. It distinguishes:

- a verified deployment;
- a clean skip because no publication dependency changed;
- an upstream deployment failure;
- a failed live-origin verification;
- a missing impact decision, which is treated as a governance failure.

## Production acceptance gates

A required Pages release must pass both structural and behavioral gates.

The structural verifier checks the exact deployed commit, complete research bundle, required bundle artifact sizes and SHA-256 values, repository-backed source contract, formal catalog order, all formal package hashes and model identities, the research boundary and the complete-backtest application shell.

After deployment, Playwright opens the public Pages origin in fresh desktop Chrome and Pixel 7 contexts. It verifies:

- exactly the three governed formal baselines;
- no Experiments navigation and no US x1.0 selector entry;
- v4.2 performance and evidence views;
- US x1.1 holdings, transaction ledger, attribution and complete evidence;
- CN x1.0 partial-evidence and unavailable-ledger states;
- no page errors, failed required resources or document-level horizontal overflow.

Traces and screenshots are retained as `pages-live-browser-evidence`.

## Formal baseline promotion contract

A formal package change is reviewed through `.github/workflows/formal-promotion.yml`. The workflow is PR-only and has read-only repository permissions. It never edits a package, changes a catalog, merges a pull request or promotes a model automatically.

Each model has an explicit manifest under `data/research/formal_promotions/` containing:

- model and package identity;
- evidence cutoff;
- original workflow run, workflow head commit, artifact ID, name and SHA-256 digest;
- original Actions artifact expiration for provenance;
- archive layout and all files required by the deterministic builder;
- the approved durable repository location.

The exact verified source ZIP bytes are retained under `data/research/formal_promotions/archive/`. The three archives total approximately 2.7 MB and remain normal binary Git objects rather than LFS pointers, so historical checkout and reproduction do not depend on expiring Actions storage or separate LFS retention.

The promotion workflow verifies that each repository ZIP SHA-256 exactly matches the original Actions artifact digest, copies it into an isolated materialization directory, safely extracts it, checks every required source path, regenerates all formal packages in a temporary directory and byte-compares the result with the proposed committed packages and catalog. It emits a JSON receipt and a human-readable diff summary.

The original Actions artifacts remain recorded as provenance, but their expiration no longer affects reproduction of accepted baselines. No newer provider bytes may be substituted: a changed or missing repository archive fails verification. Introducing or replacing a durable archive requires a reviewed PR with matching manifest, digest and byte-exact package reproduction.

A short-lived branch-only workflow was used once to download the three exact artifacts, verify their fixed SHA-256 values and commit the ZIP bytes to the governance branch. That workflow was removed before merge; no archive-writing workflow or elevated contents permission remains on `main`.

## Browser runtime caching assessment

Node package downloads already use the package-manager cache. The production deployment continues to install the Playwright Chromium runtime with `--with-deps` for each required release. A shared browser binary cache is intentionally not introduced because Playwright browser revisions and Linux system dependencies must remain aligned with the checked-in lockfile and current runner image.

Caching may be reconsidered after measuring deployment cost, preferably through a pinned and reviewed runner image or an explicit Playwright browser revision cache key. Any optimization must preserve the same fresh-context, public-origin acceptance semantics.
