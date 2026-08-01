# QQQI / QQQ / TQQQ research result and notebook policy

Last updated: 2026-08-02

## Purpose

This document defines how the QQQI / QQQ / TQQQ research line preserves experimental evidence, explains decisions and keeps human-readable notebooks current.

The objective is to prevent three common failures:

1. a result exists only in a temporary GitHub Actions artifact;
2. the experiment ledger and result report disagree;
3. a notebook continues to show an older candidate after the strategy lineage has moved on.

## Canonical research bundle

Every retained or rejected experiment must have the following durable records.

| Layer | Required record | Purpose |
|---|---|---|
| Contract | `configs/research_paradigms/*.yaml` | Frozen hypothesis, data boundary, execution convention and promotion gates |
| Implementation | `src/research/` and `scripts/` | Reproducible strategy and evidence generation |
| Tests | `tests/` | State, timing, cost and attribution invariants |
| Raw evidence | GitHub Actions artifact | Daily traces, diagnostics, coverage, run record and evidence manifest |
| Durable snapshot | `docs/research/snapshots/*.json` | Compact machine-readable metrics and artifact identifiers that remain after artifact expiry |
| Result report | `docs/research/*result*.md` | Human interpretation, attribution, limitations and decision |
| Experiment ledger | `docs/research/qqqi_qqq_tqqq_experiment_ledger.md` | Complete lineage and current decision state |
| Notebook | `notebooks/*.ipynb` | Visual inspection of equity, drawdown, states, buy/sell points and event studies |

A strategy is not considered fully recorded until all applicable layers are present.

## Notebook roles

Two notebook roles are deliberately separated.

### Immutable experiment notebook

`notebooks/16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb`

This notebook is the historical v4.1 review. It preserves the v4.1 architecture, its buy/sell signals, event study and long-history attack-layer analysis. It should not be silently rewritten to make v4.1 appear to have been designed with later information.

Corrections to calculation errors are allowed, but any correction must be documented in the experiment ledger and result report.

### Rolling current-strategy notebook

`notebooks/17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb`

This is the current comparison notebook. It must be updated whenever one of the following occurs:

- a new candidate is retained for monitoring;
- a candidate is rejected or promoted;
- the canonical snapshot changes;
- a prospective monitoring review is completed;
- a material correction changes published metrics or signals.

The rolling notebook must always show:

- the current frozen baseline and active challenger;
- complete portfolio metrics;
- equity and drawdown comparison;
- state allocations and state-path equality checks;
- signal date versus next-open execution date;
- QQQI, QQQ and TQQQ executed buy/sell points;
- signal-level 5/10/20/40-session diagnostics where applicable;
- prospective observations since the declared monitoring boundary;
- a clear research-only / trade-ready status.

## Saving experimental results

GitHub Actions artifacts are the full raw evidence source, but they are not the only durable record because artifacts expire.

For every completed experiment:

1. upload full evidence through the experiment workflow;
2. record workflow run, artifact ID and SHA-256 digest in the result report;
3. add the experiment decision to the ledger;
4. save the primary metrics and evidence identifiers in a compact JSON snapshot;
5. update the rolling current-strategy notebook when the experiment changes the active comparison set;
6. keep rejected hypotheses in the ledger so they are not repeatedly rediscovered and retested.

The current canonical compact snapshot is:

`docs/research/snapshots/qqqi_vxn_v4_1_v4_2_2026-07-31.json`

## Notebook refresh procedure

Run from the repository root:

```bash
uv sync --frozen --extra dev
uv run python scripts/refresh_qqqi_vxn_current_notebook.py
```

Optional end-date override:

```bash
QQQI_VXN_NOTEBOOK_END_DATE=2026-08-15 \
uv run python scripts/refresh_qqqi_vxn_current_notebook.py
```

The refresh command must:

- execute the rolling notebook from a clean kernel;
- fail on any notebook error;
- preserve generated tables and figures in the committed `.ipynb`;
- stamp the notebook metadata with the stable snapshot hash, contract hashes, execution mode and data boundary;
- avoid volatile timestamps or commit identifiers that would create meaningless notebook diffs;
- validate that the notebook contains no error outputs;
- leave the immutable v4.1 notebook unchanged.

## Pull-request completion rule

A pull request that changes any of the following paths must update or explicitly confirm the rolling notebook:

- `configs/research_paradigms/qqqi_qqq_tqqq_*`;
- `src/research/vxn_*` or `src/research/vix_*`;
- `scripts/run_qqqi_*`;
- `docs/research/qqqi_qqq_tqqq_experiment_ledger.md`;
- `docs/research/snapshots/qqqi_vxn_*`.

The research-bundle validation workflow checks this contract. A PR may deliberately leave the notebook unchanged only when the change is non-economic, such as formatting, comments or tests, and the PR description must state why.

## Current status

As of the 2026-07-31 evidence snapshot:

- frozen baseline: `qqqi_qqq_tqqq_vxn_leverage_v4_1`;
- active challenger: `qqqi_qqq_tqqq_vxn_bridge_v4_2`;
- prospective boundary: 2026-08-01;
- both candidates remain `research_only=true` and `trade_ready=false`;
- no additional retrospective factor, threshold or bridge-weight search is permitted on the same sample.

## Initial rolling-notebook validation

The first rolling notebook execution was completed in PR #298. The research-bundle workflow successfully:

- linted and compiled the maintenance scripts;
- passed the bundle validation tests;
- recomputed the frozen v4.1 and v4.2 comparison from live market data;
- generated and saved equity, drawdown and executed-trade outputs;
- verified that every code cell executed and that no error output was present;
- committed the executed `.ipynb` back to the PR branch;
- uploaded an independent executed-notebook artifact for audit.
