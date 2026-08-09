# Alpha Engine CI governance

Alpha Engine uses four CI tiers. A red required check must identify a defect that the current pull request can directly correct; research evidence and release promotion remain strict, but they run at the stage where their prerequisites exist.

## Tier 1 — required pull-request checks

Repository-local, deterministic checks for source, contracts, affected tests and static frontend output. They must not depend on an artifact selected only by an old workflow run ID. Cross-run data may be used only through an explicit durable evidence contract outside the required PR path.

## Tier 2 — main integration and release

Formal package promotion, Pages assembly, live-origin browser acceptance and release verification. These checks consume validated candidate artifacts and remain fail-closed on `main` or explicit release execution.

## Tier 3 — research and evidence

Model experiments, provider refreshes, optimization grids, robustness work and prospective evidence. They must be path-scoped, scheduled or manually dispatched. A missing or expired historical artifact is an evidence-health failure, not a reason to fail an unrelated frontend or documentation pull request.

## Tier 4 — advisory diagnostics

Dependency, external-source and operational-health signals. They remain visible and retained. Promotion to a blocking gate requires an explicit repository policy and a reproducible product or release risk.

## Machine-readable inventory

`scripts/check_ci_governance.py` scans every workflow and writes `artifacts/ci-workflow-inventory.json`. The inventory records:

- workflow name and path;
- governance tier and blocking policy;
- triggers, branches, path filters and dispatch inputs;
- uploaded artifact names;
- action and Node.js versions;
- hard-coded cross-run IDs;
- warnings and blocking governance violations.

The core CI enforces the following drift rules:

1. every workflow must have a name and trigger;
2. required PR workflows must listen to pull requests;
3. required PR workflows cannot contain hard-coded numeric cross-run artifact IDs;
4. research/evidence workflows that listen to pull requests must use path filters.

Action-major and Node.js modernization are recorded as warnings so old specialized workflows can be upgraded when edited without converting repository-wide runtime migration into unrelated PR noise.

## Reviewed formal-refresh performance contract

The reviewed formal-refresh workflow keeps one promotion transaction while
removing avoidable work from its critical path:

1. US and CN selected-pool providers build in separate matrix jobs.
2. A provider cache is reusable only for an exact market, requested cutoff,
   pool/reference contract, universe, dependency lock and provider
   implementation identity. Its manifest, normalized CSV tree and Qlib tree are
   sealed and reverified after artifact transfer.
3. The independent A/B ranker reproductions run concurrently into separate
   namespaces; both outputs remain mandatory inputs to the append-only verifier.
4. Market Evidence may reuse a prior market tree only when the exact provider
   manifest, formal packages, factor library and implementation identity match.
   Otherwise it rebuilds; US and CN builds remain isolated and can run together.
5. The repository must explicitly allow the trusted main/schedule workflow to
   create its reviewed refresh PR. The workflow still waits for required PR
   checks before merging. GitHub does not expose this administrator setting to
   the workflow token, so repository administration owns the setting and the
   actual draft-PR creation remains the fail-closed enforcement point.
6. Changes to frontend validation scripts, application source, dependency locks
   and build/type configuration trigger both the PR contract gate and the
   reviewed main refresh.

Every cache or incremental path remains `research_only=true` and
`trade_ready=false`. A missing, incomplete or tampered identity fails closed; it
never falls back to an ungoverned cache hit.
