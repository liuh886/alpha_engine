# A1 operating review runbook

A1 (20-session operating acceptance) remains **BLOCKED**. This runbook adds the
missing Owner-controlled, hash-bound review declaration mechanism. It does not
accept A1, sign anything, or qualify a session by itself. A1 stays BLOCKED until
**20 eligible sessions per market are collected on time** and a valid declaration
exists for each reviewed observation.

Research only: every declaration is written with `research_only=true` and
`trade_ready=false`. No agent may sign for the Owner.

## Where an observation comes from

The existing workflow `.github/workflows/formal-backtest-refresh.yml` produces
the observation in its **Capture operating acceptance observation** step
(`actions/github-script`). It writes
`artifacts/formal-refresh/operating-observation.json` and uploads it, together
with the bounded evidence, as the artifact
`formal-backtest-refresh-<run_id>-attempt-<run_attempt>`. The identity of a
review is exactly `<run_id>:<run_attempt>`.

The existing collector (`alpha ops acceptance --collect-repository ...`, backed
by `collect_operating_review`) already downloads that artifact, verifies the
archive digest/size, and writes an Owner-reviewable `review-draft.json` next to
the observation. No new scheduler, daemon, database or workflow is introduced.

## What the Owner reviews per observation

For one exact `run_id:run_attempt`, the Owner checks:

1. The observation identity, `expected_cutoffs` / `actual_cutoffs`, collection
   blockers and the publication outcome.
2. The final Actions metadata for that exact attempt (conclusion, jobs).
3. The operations snapshot and the sealed decision/delivery evidence for every
   active strategy, including cadence and freshness.
4. The operating inputs that bound the observation (`plan/plan.json`,
   `strategy-fan-in-receipt.json`, provider manifests).
5. The real manual-intervention count they performed during that observation.
   There is no default: the Owner supplies the exact non-negative integer.

The tool re-hashes every one of these files at record time. If any file is
missing or its sha256 differs from the draft, recording fails closed.

## Record a declaration

Use the review draft exactly as the existing collector wrote it. Replace the
placeholders with the Owner's real values; `--manual-interventions 0` below is
only a syntax example, never a default.

```powershell
uv run --frozen python -m scripts.record_operating_review record `
  --observation-root artifacts/product-v1-1277/latest/source `
  --run-id <run_id> --run-attempt <run_attempt> `
  --draft artifacts/product-v1-1277/latest/review-draft.json `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json `
  --manual-interventions <owner_count> `
  --reviewed-by <owner_name> `
  --cadence-and-freshness-verified
```

Use `--observation <path>` instead of `--run-id/--run-attempt/--observation-root`
when the observation artifact path is already explicit.

If no draft exists, the same command accepts explicit bindings:

```powershell
uv run --frozen python -m scripts.record_operating_review record `
  --observation <path/to/operating-observation.json> `
  --declarations <path/to/review-declarations.json> `
  --final-actions-metadata <path/to/final-actions-metadata.json> `
  --operations-snapshot <path/to/operations-snapshot.json> `
  --decision-delivery-evidence <path/to/decision-delivery-evidence.json> `
  [--operating-inputs <path/to/operating-inputs.json>] `
  --manual-interventions <owner_count> `
  --reviewed-by <owner_name> `
  --cadence-and-freshness-verified
```

The store is keyed by `<run_id>:<run_attempt>` and records the observation
sha256, every bound file hash, `reviewed_at`, the declaration schema version,
the research boundary and a declaration digest. Output is deterministic
(sorted keys, stable formatting).

## Verify declarations

```powershell
uv run --frozen python -m scripts.record_operating_review verify `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json
```

`verify` re-hashes the observation and every bound file at the current revision
and fails closed on any drift, missing binding, invalid digest, malformed
reviewer/intervention value or research-boundary violation.

Acceptance still runs through the existing authority:

```powershell
uv run --frozen alpha ops acceptance `
  --input-root artifacts/product-v1-1277/latest `
  --declarations artifacts/product-v1-1277/latest/review-declarations.json `
  --through <completed_session>
```

`build_acceptance_report` now re-verifies every binding in a declaration before
counting it, so a drifted or malformed declaration cannot become a qualified
session.

## Append-only guarantee

A declaration is immutable once recorded:

- re-recording an identical declaration is a no-op and leaves the store bytes
  unchanged;
- re-recording the same `<run_id>:<run_attempt>` with any different content is
  refused (`conflicting declaration already exists ...; the store is
  append-only`);
- `verify` rejects any edited declaration, observation or bound file.

To correct a review, record a new declaration under a different observation
identity. Do not rewrite history.

## Status and limits

- **A1 remains BLOCKED.** No declaration was recorded by the change that added
  this runbook; the declaration store is empty.
- The current re-audit is `docs/evidence/product_v1/launch_2026-11-08/a1-independent-reaudit.json`:
  17 observed / 0 qualified sessions per market, `manual_interventions: null`,
  `collected_retroactively_today: true`, `on_time_daily_collection_claimed:
  false`. This runbook does not change those facts.
- An Agent cannot sign for the Owner. The Owner must review the exact evidence
  and supply the reviewer name and manual-intervention count themselves.
- Declarations record review evidence only. They do not publish private
  research, authorize trade execution, register a strategy, or certify A1.
