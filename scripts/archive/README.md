# Archived modules (not on any active path)

These modules are retained for historical reference and manual diagnosis only.
They are **not** referenced by any test, Makefile target, CI workflow, or active
pipeline. Live code must never import, schedule or reference them.

The machine-readable mapping (module, original path, archived path, reason)
lives in [`ARCHIVE_MANIFEST.json`](ARCHIVE_MANIFEST.json). It also records the
advisory-dead modules that intentionally stay outside the archive because
sealed evidence or a notebook still names them.

The CI governance dead-module advisory excludes this directory: an archived
module is history, not a live candidate.

## Earlier manual entries

| Script | Purpose |
|---|---|
| `debug_runs.py` | Manually inspects `mlruns/**/report_normal_1day.pkl` backtest reports (mlruns is no longer the primary path). |
| `debug_jobs.py` | Manually polls `src/assistant/job_service.py` running jobs (the library itself stays; only this CLI wrapper is archived). |

Note: the `explore_*.py` early-research scripts (CSI300/topk/label/detrend
exploration) are intentionally **not** part of the repo — they predate the
2026-07-24 main sync and live under the local `.git/info/exclude` list.
