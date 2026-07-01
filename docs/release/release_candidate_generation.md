# Release Candidate Generation

> Status: active
> Date: 2026-07-01

## Overview

`scripts/generate_release_candidate.py` is the canonical entrypoint for producing
a deterministic, auditable release-candidate artifact bundle for one market.

The script loads the **real** LGBMRegressor T+10 pipeline from the workflow
config and attempts every pipeline stage in order:

1. Config loading & identity (git revision, uv.lock checksum)
2. Qlib initialisation
3. Snapshot discovery via canonical ``DataSnapshot`` API
4. Walk-forward validation
5. Final model training (canonical ``DataHandler.DK_L`` label key)
6. Vectorized backtest with T+10 benchmark and genuine top-bottom spread
7. Model/evidence artifact bundling
8. Frontend-build evidence verification
9. Release-manifest writing (only when all checks pass)

If any stage is unavailable or fails, a structured `release_failure_report.json`
is written and the script exits nonzero — resources are never fabricated.
Research artifacts from prior stages are preserved on disk (e.g., a missing
frontend build does not erase valid model/evidence artifacts).

## Command

```bash
# Generate US-only candidate
uv run python scripts/generate_release_candidate.py \\
    --candidate v0.1.0-rc1 --market us
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--candidate` | Yes | Release-candidate identifier (e.g. `v0.1.0-rc1`) |
| `--market` | Yes | Target market: `us` or `cn` |
| `--frontend-evidence` | No | Existing current-revision evidence JSON; when omitted, the generator runs `npm run build` and records it |

## Artifact Layout

```
artifacts/
├── release_candidate/{candidate}/
│   ├── release_manifest.json           (on success)
│   └── release_failure_report.json     (on failure)
├── evidence/{candidate}/
│   ├── {market}-backtest-evidence.json
│   └── {market}-signal-evidence.json
└── model_artifacts/{market}-{candidate}/
    ├── model.pkl
    ├── predictions.csv
    ├── labels.csv
    ├── diagnostics.json
    └── manifest.json
```

## Manifest Contents

`release_manifest.json` includes:

| Section | Content |
|---------|---------|
| `schema_version` | `"1"` — immutable schema identifier |
| `release_candidate_id` | Exact candidate identifier (e.g. `v0.1.0-rc1`) — no prefix added |
| `created_at` | UTC ISO-8601 timestamp |
| `code_identity` | Git HEAD revision + `uv.lock` SHA-256 |
| `metric_schema` | v1 required-metrics field list |
| `gate_policy` | T48 release gate thresholds |
| `markets` | Per-market snapshot / model / evidence references with SHA-256 checksums |
| `windows` | Train / valid / test date ranges from workflow config |
| `walk_forward` | Aggregated walk-forward IC metrics and per-split details |
| `backtest` | Return/risk metrics from vectorized backtest |
| `spread` | Top-bottom spread tracking metadata |
| `frontend_build` | Frontend-build evidence reference (required — generation fails if absent) |
| `artifact_paths` | All generated artifact relative paths |
| `missing_metrics` | Required metrics that could not be produced, with reasons |

## Failure Semantics

| Failure Mode | `error_type` | Exit code |
|---|---|---|
| Not a git repository | `GitRevisionUnavailable` | 1 |
| `uv.lock` missing | `LockfileMissing` | 1 |
| Workflow YAML missing | `ConfigNotFound` | 1 |
| Qlib initialisation fails | `QlibInitError` | 1 |
| Trading calendar unavailable | `CalendarUnavailable` | 1 |
| No valid DataSnapshot in canonical store | `NoValidSnapshot` | 1 |
| Published snapshot quality not 'pass' | `SnapshotQualityFailed` | 1 |
| Snapshot manifest missing from store | `SnapshotManifestMissing` | 1 |
| Walk-forward pipeline fails | `WalkForwardError` | 1 |
| Walk-forward produces no splits | `WalkForwardNoSplits` | 1 |
| Model training / prediction fails | `TrainingError` | 1 |
| Empty after finite-value filtering | `EmptyAfterFiniteCheck` | 1 |
| Insufficient alignment coverage | `InsufficientAlignmentCoverage` | 1 |
| Empty predictions or labels produced | `EmptyPredictions` / `EmptyLabels` | 1 |
| Misaligned predictions/labels | `MisalignedData` | 1 |
| Non-finite predictions/labels | `NonFinitePredictions` / `NonFiniteLabels` | 1 |
| Backtest pipeline fails | `BacktestError` | 1 |
| Backtest produced no metrics | `MissingRequiredMetrics` | 1 |
| Bottom-N spread backtest fails | `SpreadComputationFailed` | 1 |
| Frontend evidence missing/invalid | `FrontendEvidenceMissing` / `FrontendEvidenceInvalid` | 1 |
| Artifact build error | `ArtifactBuildError` | 1 |
| Unrecognised market | — | 1 |

Each failure report is a JSON object at
`artifacts/release_candidate/{candidate}/release_failure_report.json` with:

| Field | Type | Description |
|-------|------|-------------|
| `candidate` | string | Candidate identifier |
| `market` | string | Target market |
| `stage_failed` | string | Pipeline stage name |
| `error_type` | string | Machine-readable error classifier |
| `error_message` | string | Human-readable error detail |
| `missing_files` | list[str] | Paths that may explain the failure |
| `suggested_fix` | string | Recommended recovery action |
| `timestamp` | string | UTC ISO-8601 timestamp |

## Verification

```bash
# Verify the generated manifest
uv run python scripts/release_gate.py --candidate v0.1.0-rc1
```

The release gate verifier (`src.release.candidate.verify_release_candidate`)
checks every checksum, identity, and metric threshold. US-only candidates are
valid (CN market is not required). Historical evidence is never substituted.

## Known Limitations

1. **Real data required.** The script requires Qlib data at `data/watchlist/`.
   Without it, every pipeline stage fails with a descriptive failure report.
   Run `uv run python scripts/collect_data.py --market us` first.
2. **US-only market support.** CN market pipeline is structurally supported but
   has not been end-to-end validated.
3. **Single-market invocation.** The script generates artifacts for exactly one
   market per invocation. To build a multi-market candidate, run once per
   market and combine manifests.

## Release Policy

This PR changes the release gate from requiring both CN and US markets to
accepting a non-empty subset of supported markets (`us`, `cn`), enabling
US-only candidates while keeping future CN support.  Historical evidence is
never substituted.  See ``src/release/candidate.py`` for the current policy
thresholds and ``test_release_candidate_gate.py`` for US-only verification
tests.
