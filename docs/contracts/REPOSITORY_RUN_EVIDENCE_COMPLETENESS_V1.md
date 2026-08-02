# Repository Run Evidence Completeness v1

## Purpose

This contract distinguishes truthful historical normalization from full-trace forward evidence. Repository Run v1 allows `equity_curve.json` to be absent, but absence must be explicit and machine-verifiable.

## Historical normalized run

A historical run may omit `equity_curve.json` only when `run.json` records `evidence_status=normalized_from_immutable_source_artifact` and the curve status `unavailable_source_artifact_did_not_retain_trace`.

The run must retain source workflow ID, artifact ID, artifact digest, exact canonical metrics and explicit prohibited actions:

- do not infer a curve from aggregate returns;
- do not replay against a different provider snapshot;
- do not restate snapshot-specific performance.

A historical normalized run can be a model's primary evidence record, but the published manifest must expose `primary_run_curve_unavailable` and any provider-snapshot gap.

## Full-trace forward run

A new accepted training/backtest run must retain:

- complete provider snapshot bytes;
- exact period or daily NAV trace;
- benchmark trace;
- target holdings;
- name-level contribution evidence;
- declared and effective parameter identities;
- source and inventory hashes.

For the current fixed-10D evaluator, the canonical trace frequency is `non_overlapping_forward_horizon`. Each trace point is tied to the signal/rebalance date and represents value after the declared forward horizon. It must not be labelled as daily NAV.

## Publication rules

- `data/research/catalog.json` binds every published model to `primary_run_id`.
- The primary run's metrics override duplicated model-card summaries in the frontend bundle.
- Curves are published only when the exact file exists and passes its inventory hash.
- Missing historical curves remain visible as blocked gates rather than silently disappearing.
- Local `metadata.db` is rebuilt from the same primary run and must reproduce its metrics and any available curve.

## Validation

`scripts/check_repository_model_runs.py` validates model/run identity, provider identity, source artifact identity, exact metrics, inventories and governed curve absence.

`scripts/check_window_trace_retention.py` validates that future completed window evidence retains period points, holdings and research-only boundaries for every evaluated candidate orientation.
