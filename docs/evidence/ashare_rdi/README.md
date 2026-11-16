# A-share RDI evidence receipts

## restricted_unlock PIT coverage and feasibility (2026-11-16)

`restricted_unlock_coverage_2026-11-16.json` is the first frozen work package
for GitHub issue #1272. It is a read-only coverage/feasibility receipt for the
`restricted_unlock` event family; it is not an E(t) series, score, forecast or
strategy registration.

The receipt records:

- the declared universe/era, selected-pool hash and current governed price cutoff;
- per-field coverage for original announcement identity, first public
  availability, source/evidence hash, story identity and de-duplication,
  effective unlock session, amendment chain and as-of-known schedule;
- archive-level universe/era/PIT membership and per-session coverage or absence;
- adapter capability gaps visible in the existing normalized event schema;
- exact gaps plus a `does_not_claim` boundary.

Unknown stays unknown. A missing record is never a zero event. The receipt is
`research_only=true`, `trade_ready=false`, and it does not qualify the other
nine RDI event families.

### Re-run

From the repository root (no provider or network call is made):

```bash
uv run --frozen --extra dev python -m src.research.ashare_rdi.phase2_audit \
  --restricted-unlock-coverage \
  --period-start 2022-01-01 --cutoff 2026-08-03 \
  --receipt-date 2026-11-16 \
  --output docs/evidence/ashare_rdi/restricted_unlock_coverage_2026-11-16.json
```

If a governed archive is later produced, pass its inputs explicitly:

```bash
uv run --frozen --extra dev python -m src.research.ashare_rdi.phase2_audit \
  --restricted-unlock-coverage \
  --records artifacts/.../events.jsonl \
  --coverage artifacts/.../coverage.json \
  --archive-manifest artifacts/.../manifest.json \
  --period-start 2022-01-01 --cutoff 2026-08-03 \
  --receipt-date 2026-11-16 \
  --output docs/evidence/ashare_rdi/restricted_unlock_coverage_2026-11-16.json
```

`--receipt-date` is required so re-runs are deterministic. The receipt records
`repository_commit` and SHA-256 hashes of the audited source/config files. The
command performs no provider call, scoring, forecast or write outside the
requested output path.

### Tests

```bash
uv run --frozen --extra dev python -m pytest tests/test_ashare_rdi_restricted_unlock_audit.py -q
uv run --frozen --extra dev ruff check src/research/ashare_rdi/restricted_unlock_audit.py \
  src/research/ashare_rdi/phase2_audit.py tests/test_ashare_rdi_restricted_unlock_audit.py
```
