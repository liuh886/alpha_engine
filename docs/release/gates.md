# Release Candidate Gates

Status: enforced, current candidate rejected
Date: 2026-06-20

## One Local and CI Command

```bash
uv run python scripts/release_gate.py --candidate rc_20260620 --run-quality-gates --evidence-dir artifacts/release_gates
```

The candidate argument is mandatory. It may be an exact manifest path or an
exact `rc_*` identifier. There is no latest, newest, or best-history fallback.
CI runs the command above verbatim after installing locked dependencies and the
Playwright Chromium prerequisite.

For candidate integrity verification without the broader quality suite:

```bash
uv run python scripts/release_gate.py --candidate rc_20260620
```

Both modes emit one JSON verdict and return nonzero on any missing, malformed,
unrelated, substituted, or failing input.

## Candidate Contract

A valid v1 ReleaseCandidate pins both CN and US identities for:

- a non-empty DataSnapshot manifest and every snapshot file checksum;
- a complete ModelArtifact manifest and every model bundle checksum;
- model-bound backtest and signal evidence with exact checksums;
- the canonical v1 release metric schema and T48 gate policy;
- the Git revision and SHA-256 of `uv.lock`;
- a frontend build evidence identity for the same revision.

All referenced paths must remain inside the project root. DataSnapshot,
ModelArtifact, evidence, metric, code, and lock identities must agree. The gate
does not consult model registries, `latest` pointers, or unrelated walk-forward
files.

## Enforced Quality Set

The one command runs and captures:

1. `python -m ruff check .`
2. `python -m mypy src/release scripts/release_gate.py`
3. `python -m pytest tests -q` with exact skipped-node accounting
4. `npm ci`
5. `npx tsc --noEmit`
6. `npm run lint`
7. `npm run test`
8. `npm run build`
9. `npx playwright test` against the freshly built Vite preview
10. `uv build`

The mypy scope is the initial typed ratchet: all new release verification code
and its CLI must remain typed while broader legacy typing debt is addressed.
The checked-in approved-skip set is empty. Any pytest runtime or collection
skip therefore fails the release gate and is listed by exact node ID and reason.

## Evidence

`artifacts/release_gates/` contains one log per command plus:

- `pytest.xml` and `pytest_skips.json`;
- `quality_gate_report.json`;
- `release_gate_verdict.json`.

Each command record includes its argv, revision, environment, working
directory, exit code, duration, output path, and output SHA-256. CI uploads the
directory even when the gate fails.

## Current Candidate

`rc_20260620` is rejected. Its legacy manifest explicitly says no formal
DataSnapshot was published and required return/risk metrics are absent. The v1
verifier also finds no exact snapshot/model/evidence checksums or code/lock
identity. The legacy manifest is retained as historical evidence and is not
rewritten to pass.
