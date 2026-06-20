# Release Candidate Signoff

Status: REJECTED
Date: 2026-06-20
Candidate: `rc_20260620`

## Machine Verdict

Run:

```bash
uv run python scripts/release_gate.py --candidate rc_20260620
```

Result: exit 1, `status: fail`.

## Blocking Findings

- No formal CN or US DataSnapshot manifest is referenced.
- No complete CN or US ModelArtifact manifest is referenced.
- Required v1 metrics, including annualized return and max drawdown, are absent.
- Backtest and signal evidence are not exact, checksummed, model-bound artifacts.
- Git revision, dependency-lock checksum, gate policy, and frontend build identity are absent.

The candidate's embedded `gates_passed: true` and PASS prose are untrusted
self-assertions. The candidate artifact remains unchanged as historical
evidence; this document records the verifier result and does not convert the
candidate to PASS.

## Signoff

No release signoff exists for `rc_20260620`. A future candidate can be signed
off only after the exact candidate verifier and the complete local/CI command
both return `status: pass` with captured evidence.
