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

`.github/ci-policy.json` is the single source for required, release and advisory
workflow membership. Both CI policy enforcement and tier inventory consume it;
unassigned workflows retain the inventory's filename-based default tier. The
workflow count budget is a ceiling and must decrease as permanent paths retire.

`scripts/check_ci_governance.py` scans every workflow and writes `artifacts/ci-workflow-inventory.json`. The inventory records:

- workflow name and path;
- governance tier and blocking policy;
- triggers, branches, path filters and dispatch inputs;
- uploaded artifact names;
- action and Node.js versions;
- hard-coded cross-run IDs;
- an advisory `dead_modules` inventory: `src/research` + `scripts` modules whose
  stem is referenced by no live file (code, tests, configs or workflows); docs
  and sealed evidence never confer life; modules already moved to a governed
  `/archive/` directory (see `scripts/archive/ARCHIVE_MANIFEST.json`) are
  write-once history and never candidates;
- warnings and blocking governance violations.

The `dead_modules` inventory is advisory only: it never fails the build and
never deletes anything. It exists so the cleanup backlog stays visible instead
of depending on one-off manual scans.

The core CI enforces the following drift rules:

1. every workflow must have a name and trigger;
2. required PR workflows must listen to pull requests;
3. required PR workflows cannot contain hard-coded numeric cross-run artifact IDs;
4. research/evidence workflows that listen to pull requests must use path filters.

Action-major and Node.js modernization are recorded as warnings so old specialized workflows can be upgraded when edited without converting repository-wide runtime migration into unrelated PR noise.

## Main history protection

The `main-history-integrity` repository ruleset targets only `refs/heads/main`
and blocks deletion and non-fast-forward updates. It has no bypass actors.
The expected payload is recorded under `branch_protection.history_ruleset` in
`.github/ci-policy.json`; live GitHub settings remain the enforcement authority.
Read active rules with `gh api repos/liuh886/alpha_engine/rules/branches/main`.

This protects retained evidence history while allowing the existing signal and
delivery workflows to append fast-forward commits. Those producers currently
push directly to main after rebasing; a blanket pull-request or global required
check rule would interrupt them. Required PR checks remain path-scoped and
formal promotion retains its exact-candidate validation and reviewed merge.
The empty `required_status_checks` list describes the absence of a global
server-enforced check rule; it does not claim that CI or review can be skipped.
The former advisory check-name list included a retired frontend job and has
been removed rather than turned into a required check that may never run.

Verify protection by reading back the ruleset, target, rules and bypass list,
and by observing a normal reviewed merge. Do not attempt destructive main
updates as a protection test. A later change to required PR/status rules must
first migrate or explicitly govern the direct-writing producers.

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
   create its reviewed refresh PR. The workflow explicitly dispatches the
   Formal Backtest Refresh contract on the exact candidate SHA and waits for
   that run before merge. This avoids relying on pull-request events created by
   `GITHUB_TOKEN`, which GitHub may leave awaiting approval. The workflow waits
   for the explicitly dispatched candidate validation before merging. GitHub
   does not expose the pull-request workflow approval setting to the workflow
   token, so repository administration still owns that setting; the exact-SHA
   dispatch is the fail-closed enforcement point for the automated publication.
6. Changes to frontend validation scripts, application source, dependency locks
   and build/type configuration trigger both the PR contract gate and the
   reviewed main refresh.

The 2026-10-22 simplification review retained both PR and explicit dispatch
validation. The PR checks a test-merge commit; dispatch checks the exact
candidate commit. Repository APIs reported `main` as unprotected, with no
applicable branch rules or rulesets. A matching candidate head does not bind
the merge base, and the repository has no governed merge queue to reuse.
Removing the PR execution would therefore remove validation of a distinct
input. This is not evidence that the existing pair eliminates every base
race. Reconsider deduplication only when an existing governed mechanism can
prove coverage of the actual merge input and a measured operating benefit;
do not substitute cancellation or a successful skip for that proof. The
[approved plan and execution record](operations/focused_core_simplification_plan_2026-10-22.md)
retain this decision and its scope. No workflow or repository protection
setting changed in this review.

Every cache or incremental path remains `research_only=true` and
`trade_ready=false`. A missing, incomplete or tampered identity fails closed; it
never falls back to an ungoverned cache hit.
