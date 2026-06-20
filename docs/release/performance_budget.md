# Performance and Resource Budget

Updated: 2026-06-20 (measured)

## Dashboard Build

| Metric | Value | Budget | Status |
|--------|-------|--------|--------|
| Build output | 1,447 KB (single inlined HTML) | < 5 MB | OK |
| Gzipped transfer size | 401 KB | < 1 MB | OK |
| Build time | 9.75s | < 60s | OK |
| Modules transformed | 2,976 | -- | -- |
| Routes (routes.ts) | 17 | -- | -- |
| API types (api-types.ts) | 101 | -- | -- |
| node_modules (dev only) | 190 MB | -- | not shipped |

The dashboard uses `vite-plugin-singlefile` to inline all JS and CSS into a
single `index.html`.  There is no separate JS/CSS bundle -- everything ships as
one file.  Gzip compression brings the transfer size to ~391 KB.

## API Cold Start

| Metric | Value | Budget | Status |
|--------|-------|--------|--------|
| Import time (`from api_server import app`) | 4.9s | < 10s | OK |
| Modules imported | ~3,150 | -- | -- |

Import warnings present at startup (non-blocking):
- Gym deprecation (should migrate to Gymnasium)
- CVXPY solver import failures for SCS and OSQP (circular import / missing algebra backend)

These warnings do not affect core API functionality.

## Test Suite

| Metric | Value | Budget | Status |
|--------|-------|--------|--------|
| Full test suite runtime | 47s | < 120s | OK |
| Tests passed | 413 | -- | -- |
| Tests skipped | 14 | -- | -- |
| Warnings | 3 | -- | -- |

## Walk-Forward Research Workflow

| Metric | Value |
|--------|-------|
| Total result files | 180 |
| CN market files | 26 |
| US market files | 154 |
| Date range | 2026-06-09 to 2026-06-19 |
| Typical CN run (16 splits) | ~15 min wall time |
| Typical CN run (12 splits) | ~10 min wall time |

A single CN walk-forward with 16 rolling splits and LightGBM training takes
approximately 10-15 minutes.  US walk-forward runs are currently failing across
all splits due to a feature-loading bug (`unexpected keyword argument 'freq'`).

## Vectorized Backtest Equivalence (T48.7)

The hermetic golden harness uses the same Qlib-shaped prediction/return frames,
calendar, TopK strategy, initial capital, and buy/sell costs for both paths.
Frozen CN and US unit fixtures compare:

- orders and daily holdings exactly;
- NAV with `rtol=1e-12`, `atol=1e-8`;
- total/annual return, drawdown, Sharpe, volatility, turnover, and transaction
  cost with `rtol=1e-12`, `atol=1e-12`;
- missing individual predictions as excluded candidates and all-missing dates as
  hold/no-trade dates.

The offline performance fixture contains 260 business dates x 200 instruments
(52,000 rows), 3% deterministic missing predictions, TopK 5, 10-step
rebalancing, 5 bps buy cost, 10 bps sell cost, and USD 1,000,000 initial NAV.
CN uses seed 4807 and US seed 4817. Values below are medians of five runs on
2026-06-20; memory is Python allocation peak measured by `tracemalloc`.

| Market | Path | Median wall time | Peak memory | Prediction-source fetches | Relative to ordinary |
|--------|------|------------------|-------------|---------------------------|----------------------|
| CN | Ordinary cold | 785.811 ms | 2,302.2 KiB | 26 | 1.00x |
| CN | Vectorized cold | 541.812 ms | 3,275.1 KiB | 1 | 1.45x |
| CN | Vectorized warm | 539.119 ms | 2,864.6 KiB | 0 | 1.46x |
| US | Ordinary cold | 665.681 ms | 2,301.7 KiB | 26 | 1.00x |
| US | Vectorized cold | 505.375 ms | 3,274.6 KiB | 1 | 1.32x |
| US | Vectorized warm | 579.184 ms | 2,865.1 KiB | 0 | 1.15x |

The measured output traces contained 245 CN / 249 US orders, 260 daily holding
snapshots, and 261 NAV points. The focused CI test fails if ordinary fetches
differ from the 26 rebalance dates, vectorized cold exceeds one fetch,
vectorized warm performs any fetch, any path exceeds 2 seconds, traced peak
memory reaches 4 MiB, or equivalence tolerances are exceeded.

| Market | Final NAV | Total return | Max drawdown | Sharpe | Volatility | Turnover | Cost |
|--------|-----------|--------------|--------------|--------|------------|----------|------|
| CN | 1,095,446.672159 | 0.095446672159 | -0.083485011137 | 1.118527065018 | 0.082013279990 | 24.5 | 0.0365 |
| US | 985,636.522582 | -0.014363477418 | -0.070265266218 | -0.117749570052 | 0.086963848620 | 24.9 | 0.0371 |

These measurements replace the previous unverified speedup statement in the
vectorized implementation and plugin description. They show lower data-call volume and a
1.15x-1.46x wall-time improvement on this workload, with higher peak Python
allocation for the vectorized path.

### Remaining Qlib Limitation

This is an adapter-level golden proof, not a full hermetic Qlib executor proof.
It does not invoke Qlib's exchange, tradability/limit rules, lot rounding, deal
price, or binary data provider. The fetch counts above are adapter prediction
source reads, not measured `D.features()` calls. A full release proof still requires immutable CN
and US DataSnapshot/ModelArtifact fixtures plus a pinned Qlib runtime and binary
provider. Until that fixture is available, these results must not be represented
as full ordinary-versus-vectorized Qlib equivalence.

## Disk Usage

| Directory | Size | Budget | Status |
|-----------|------|--------|--------|
| `data/` | 176 MB | < 500 MB | OK |
| `mlruns/` | 149 MB | < 1 GB | OK |
| `artifacts/` | 1.8 GB | < 5 GB | OK |
| `artifacts/walk_forward/` | ~1 MB (180 JSON files) | -- | -- |
| `artifacts/mlflow.db` | 1.6 MB | -- | -- |
| `artifacts/engine_state.db` | 600 KB | -- | -- |

Artifacts contain walk-forward results, SQLite databases (engine state, factor
registry, signal history, MLflow tracking), and research run metadata.  The bulk
of artifact size (1.8 GB) comes from accumulated research run outputs and model
files.

## Memory Considerations

| Scenario | Estimated Peak RAM |
|----------|--------------------|
| Qlib data loading (full CN watchlist, 211 stocks x 5 years) | ~500 MB |
| Walk-forward training (16 sequential LightGBM fits) | ~1-2 GB |
| API server idle | ~200 MB |
| Dashboard | 0 MB (static HTML, no server-side memory) |
| System total / available at measurement time | 13.9 GB total / 2.6 GB available |

The machine has 14 GB RAM with ~81% in use at measurement time.  Walk-forward
runs that load full Qlib datasets plus train models can push memory usage to
the limit.  Running multiple concurrent research workflows is not advisable on
this hardware.

## Known Performance Limitations

1. **Walk-forward runtime**: 10-15 min for a full CN validation is acceptable
   for batch research but too slow for interactive exploration.  Caching trained
   models or incremental re-training would reduce this.

2. **Artifacts growth**: Currently 1.8 GB and growing with each walk-forward
   run.  The 180 walk-forward result files in `artifacts/walk_forward/` alone
   are small (~1 MB total), but accumulated model outputs and MLflow data
   increase over time.  An archival or rotation policy is recommended.

3. **API cold start at ~5s**: Acceptable for a long-running server process but
   noticeable for CLI one-shot commands.  The 3,150-module import chain includes
   heavyweight dependencies (pandas, numpy, qlib, cvxpy, lightgbm, xgboost).

4. **Memory pressure**: With 14 GB RAM and 82% baseline utilization, concurrent
   operations (API + walk-forward + dashboard dev) risk OOM.  The CVXPY solver
   import failures may also cause fallback to less efficient code paths.

5. **US walk-forward broken**: All US market walk-forward splits currently fail
   with `unexpected keyword argument 'freq'` in feature loading.  This is a
   functional bug, not a performance issue, but it means US market validation
   cannot complete.

6. **Full Qlib backtest proof pending**: T48.7 currently proves the adapter-level
   signal materialization and portfolio accounting contract. Exchange execution
   equivalence against immutable CN/US Qlib binary snapshots remains pending.

## Out-of-Budget Areas

None currently within documented budgets.  All measured metrics are within
their respective limits.
