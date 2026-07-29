# Static-to-PIT Alpha Decomposition Runbook

## Purpose

This runbook implements Issue #187. It explains why the fixed LightGBM and
XGBoost ranker results change when the research universe moves from a
retrospective static list to window-start point-in-time Nasdaq-100 membership.
It is a research-only diagnosis, not a new model search.

## Provider separation

The published endpoints were not produced on the same provider identity:

- the #183 static S/S result used the original static-universe provider;
- the authoritative PIT result used the repaired historical-membership provider.

The runner therefore separates two questions:

1. **Endpoint reproduction** — reproduce the published S/S result on its original
   provider and reproduce P/P on the repaired provider;
2. **Controlled membership decomposition** — run S/S, S/P, P/S and P/P on the
   same repaired provider.

This prevents the KLAC/full-history repair and other provider changes from being
silently attributed to membership. The report includes a separate provider
repair effect from published S/S to controlled repaired-provider S/S.

The CLI requires the exact committed provider identities:

| Role | Required identity |
| --- | --- |
| Published static reference | `66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8` |
| Controlled repaired provider | `6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407` |

A different manifest-bound provider fails before any model fitting.

## Frozen matrix

| Cell | Training membership | OOS membership | Interpretation |
| --- | --- | --- | --- |
| S/S | Static curated | Static curated | Controlled static endpoint |
| S/P | Static curated | PIT NDX | OOS opportunity-set effect |
| P/S | PIT as-of | Static curated | Training and label effect |
| P/P | PIT as-of | PIT NDX | Authoritative PIT endpoint |

For every metric:

- OOS effect = S/P - S/S;
- training/label effect = P/S - S/S;
- interaction residual = P/P - S/P - P/S + S/S;
- controlled total gap = P/P - S/S.

The three effects must reconcile exactly to the controlled total gap.

## Command

Generic command:

```bash
uv run python scripts/run_static_to_pit_alpha_decomposition.py \
  --static-reference-provider-uri <original-static-provider> \
  --decomposition-provider-uri <repaired-pit-provider>
```

The committed evidence records these Windows paths for the original run:

```powershell
uv run python scripts/run_static_to_pit_alpha_decomposition.py `
  --static-reference-provider-uri "D:\Documents\GitHub\alpha_engine\data\providers\us" `
  --decomposition-provider-uri "D:\Documents\GitHub\alpha_engine_ndx_backfill_data_cf8c77f\data\providers\us"
```

The paths are accepted only when their manifests match the two identities above.
The runner also fails closed if the published S/S or authoritative P/P endpoint
does not reproduce the committed rounded metrics.

If the repaired directory is no longer present, rebuild an isolated provider
before running the decomposition:

```powershell
uv run python scripts/build_ndx_window_start_provider.py `
  --base-data-root "D:\Documents\GitHub\alpha_engine" `
  --output-data-root "D:\Documents\GitHub\alpha_engine_ndx_backfill_data_cf8c77f" `
  --overwrite
```

After a rebuild, verify that the resulting identity is still
`6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407`.
A different identity is new data and must not silently replace the committed
provider in this decomposition.

## Outputs

The default output directory is:

```text
artifacts/evidence/static_to_pit_alpha_decomposition/
```

It contains:

- `reference_static/` — canonical static endpoint reproduction;
- `per_window/<window>.json` — four-cell reports and diagnostics for each window;
- `evidence_manifest.json` — provider, spec, membership and contract identities;
- `aggregate.json` — stability, provider effect, four-cell effects and diagnostics;
- `decision.json` — final research boundary;
- `report.md` — answer-first summary.

Diagnostics include:

- Top-15 selection overlap by rebalance date;
- common-name score rank correlation and percentile migration;
- processed gain-bin migration on common training rows;
- contributions from common, static-only, PIT-only, future-entry and historical-exit names;
- concentration of the static-minus-PIT contribution gap;
- common-intersection-universe comparison;
- per-window interaction residuals.

## Stop rule

The observed 2024H1--2025H2 windows are development-observed. This runner exposes
no parameters for tree calibration, feature windows, score orientation, Top-K,
blend weights, costs, thresholds or universe selection.

The committed post-run decision remains:

```text
stop_existing_ohlcv_ranker_family
```

A later research challenge must introduce a genuinely new economic information
set and an untouched evidence plan. Favorable S/P or P/S diagnostics cannot
justify promotion.
