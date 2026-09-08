# Archived helper scripts (not on any active path)

These scripts are retained for manual diagnosis only. They are **not**
referenced by any test, Makefile target, CI workflow, or active pipeline.
Do not add new callers; delete outright once nobody needs them.

| Script | Purpose |
|---|---|
| `debug_runs.py` | Manually inspects `mlruns/**/report_normal_1day.pkl` backtest reports (mlruns is no longer the primary path). |
| `debug_jobs.py` | Manually polls `src/assistant/job_service.py` running jobs (the library itself stays; only this CLI wrapper is archived). |

Note: the `explore_*.py` early-research scripts (CSI300/topk/label/detrend
exploration) are intentionally **not** part of the repo — they predate the
2026-07-24 main sync and live under the local `.git/info/exclude` list.
