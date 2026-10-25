# Local Agent delivery contract — Direction A, v1.0

**Owner-selected positioning (2026-10-25):** a single-operator
professional quantitative research workstation, consistent with accepted
ADR-0003. Development acceptance remains reviewable in draft PR #1276.

**Scope:** Alpha Engine product completion. This is a task-handoff template,
not an automation authorization or executable runbook by itself.
Current authority: `AGENTS.md`, `docs/product/strategy_console.md`, existing
frozen research/evidence contracts and GitHub Issues. Maintain
`research_only=true` and `trade_ready=false`.

## Roles and decisions

- **Product owner (human):** has selected Direction A, sets priorities, and
  reviews existing public/Pro trust boundaries,
  reviews evidence and explicitly approves changes to active strategy identities,
  entitlements, trading behavior or product scope.
- **Product designer / architect (ChatGPT):** inspects source/evidence, states
  assumptions, decomposes epics into narrow Issues, records acceptance,
  analyzes PR results, and recommends merge/reject/hold. It does **not** treat
  theoretical ideas or CI success as real user/market acceptance.
- **Local coding Agent:** implements exactly one accepted, well-bounded GitHub
  Issue per branch, runs tests and provides a self-review + evidence receipt,
  and opens a PR. No direct production/main mutation or automatic merge.
- **CI/governance:** machine-checkable contract gates; do not replace owner UAT,
  independent research validation or 20-session operating acceptance.

## Required input for each Issue

1. **Observed user problem and evidence** (current main SHA, screenshot/log/
   receipt, or explicit `hypothesis_needs_UAT`).
2. **Outcome**: what user question gets answered or blockage removed.
3. **Exact authorized scope**: modules, affected authority, existing entrypoint,
   dependencies and explicit out-of-scope behavior.
4. **Implementation boundaries**: preserve stable strategies and manifests;
   no second scheduler/registry/db/CI job, reactivated obsolete UI, or secret
   browser data. No numeric lookahead in research.
5. **Acceptance**: concrete positive + negative scenario, cutoff/identity/PIT
   contract and task-based end-to-end observable proof.
6. **Validation**: targeted unit/contract + existing release gates, negative
   cases, performance where relevant and exact run/build receipt.
7. **Rollback**: how to revert without changing sealed research evidence or
   losing valid retained current decisions.
8. **Definition of Done**: implementation, tests, observed evidence, docs,
   failed cases and a reviewable PR. Mark undecidable claims as blocked,
   not as passed.

## Direction A constraints for local implementation

- Two modes, one operator: **local governed CLI research** and the **read-only
  Strategy Console**. No browser research IDE, subscription payment,
  multi-tenant users or autonomous trade path in v1.
- Existing public historical formal evidence and current protected
  Supabase/RLS/Pro operations remain secure; one-owner scope does not mean
  relaxing current privacy or rewriting entitlements.
- Four accepted strategies only; no silent new strategy, weights, model
  registry or extra permanent GitHub Actions workflow.
- RDI is unvalidated independent research; do not add scores/positions to
  live formal models to imply its prediction accuracy.
- One task = one scoped Issue = one PR and an exact evidence packet. In
  particular, a simulation or green CI alone cannot close an operating
  acceptance issue.

## Agent workflow

```text
GitHub scoped Issue (ready)
  -> inspect current main + authoritative docs and callers
  -> post plan with affected paths, failure cases, scope exclusions
  -> create feature branch from current main
  -> implement smallest correct vertical slice
  -> run targeted tests + required affected quality gates
  -> attach output hashes, exact dates, screenshots/trace and observed before/after
  -> open PR linking Issue, record remaining blockers
  -> architecture/product review -> owner approval -> merge
  -> verify deployed result and update original Issue
```

The agent MUST NOT silently modify strategy weights, models, costs, universe,
benchmark, PIT policy, active registry, RLS entitlement or formal identity while
performing a design or UI task. Request a separate explicitly approved issue
if one is necessary. Do not turn archived experiments into supported product
paths or add compatibility fallbacks to hide incomplete evidence.

### Mandatory PR write-up (copyable)

```markdown
## User outcome / exact Issue
## Main commit, evidence cutoff and active model identities inspected
## Changed paths and why each was necessary
## Contracts kept invariant (PIT, public/private, read-only, research-only)
## Positive/negative end-to-end user journeys verified
## Unit/contract/CI and browser evidence links (exact run IDs)
## Performance/operations before vs after (when relevant)
## Remaining blockers and failed tests (no false-green)
## Rollback and post-merge verification
## Product-owner decisions needed (if any)
```

### Quality review / task rejection

Reject or defer a PR if it only adds new UI but cannot point to a user task
that was previously blocked; calls an old route a current product feature;
counts synthetic fixtures as historical OOS performance; presents old snapshots
as new; duplicates authority; widens workflow/security surface without retiring
something; modifies a frozen model without approval; hides failed/outdated
evidence; or asserts release readiness based only on a CI pass.

## Task prioritization (do not supersede Issue #1074)

**Work sequence:** W0 #1278 docs authority; W1 #1277 real multi-session
operating acceptance, with #1279 security-negative audit; W2 #1279
four-strategy desktop/mobile task UAT; W3 #1282 for
minimal reproducible accepted US/CN research (upstream #324/#325/#826 only if needed); W4 #1281 owner runbook,
release receipt and rollback. See
[`v1_direction_a_agent_roadmap_2026-10-25.md`](v1_direction_a_agent_roadmap_2026-10-25.md).
Evidence gathering for W1/W2 may overlap; material code fixes each get
their own narrow Issue, not indiscriminate refactors.

- P0: operating session acceptance; source/decision/delivery truth;
  authorization and static boundary; documentation authority reconciliation.
- P1: focused task-based Overview -> Detail -> Instrument -> Status UAT and
  observed UX fixes; reproducible approved US/CN research slice.
- P2: measured performance & accessibility polish; optional new modules only
  once v1 acceptance is satisfied.

Use one responsible Issue owner and one existing evidence authority per
deliverable. Update the Issue with explicit `ready / blocked / done` and
manifest/run links. A docs/architecture proposal PR does not authorize local
agent deployment by itself.

## Required evidence in every local Agent PR

Include an operator-facing before/after result, changed authoritative paths,
exact source cutoff and SHA, test **PASS/FAIL/BLOCKED/NOT_TESTED** matrix,
one negative path, new permanent complexity introduced and what was removed,
release/rollback method, and observed operating/browser receipts when claimed.
Never turn unknown data into a fake zero, a fixture into real prospective
evidence, or the owner's product-selection approval into production release
authorization.
