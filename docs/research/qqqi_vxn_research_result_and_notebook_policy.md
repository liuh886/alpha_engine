# QQQI / QQQ / TQQQ research result and notebook policy

Last updated: 2026-08-02

## Purpose

This document defines how the QQQI / QQQ / TQQQ research line preserves experimental evidence, explains decisions, generates alerts and keeps human-readable notebooks current.

The objective is to prevent four common failures:

1. a result exists only in a temporary GitHub Actions artifact;
2. the experiment ledger and result report disagree;
3. a notebook continues to show an older candidate after the strategy lineage has moved on;
4. a notification is generated from logic that differs from the frozen strategy monitor.

## Canonical research bundle

Every retained or rejected experiment must have the following durable records.

| Layer | Required record | Purpose |
|---|---|---|
| Contract | `configs/research_paradigms/*.yaml` | Frozen hypothesis, data boundary, execution convention and promotion gates |
| Current-baseline pointer | `configs/research_paradigms/qqqi_qqq_tqqq_current_baseline.yaml` | Declares which experiment new challengers must beat |
| Implementation | `src/research/` and `scripts/` | Reproducible strategy and evidence generation |
| Tests | `tests/` | State, timing, cost, attribution and alert invariants |
| Raw evidence | GitHub Actions artifact | Daily traces, diagnostics, coverage, run record and evidence manifest |
| Durable snapshot | `docs/research/snapshots/*.json` | Compact machine-readable metrics and artifact identifiers that remain after artifact expiry |
| Result report | `docs/research/*result*.md` | Human interpretation, attribution, limitations and decision |
| Experiment ledger | `docs/research/qqqi_qqq_tqqq_experiment_ledger.md` | Complete lineage and current decision state |
| Notebook | `notebooks/*.ipynb` | Visual inspection of equity, drawdown, states, buy/sell points and experiments |

A strategy is not considered fully recorded until all applicable layers are present.

## Current baseline policy

From 2026-08-02:

- current research baseline: `qqqi_qqq_tqqq_vxn_bridge_v4_2`;
- historical signal comparator: `qqqi_qqq_tqqq_vxn_leverage_v4_1`;
- transaction cost: 10 basis points per turnover unit;
- both remain `research_only=true` and `trade_ready=false`;
- v4.2's post-result origin remains recorded;
- no retrospective bridge-weight grid is allowed.

The baseline change reflects lower turnover and stronger net results under an identical signal trace. It is not a claim that v4.2 predicts better than v4.1.

## Notebook roles

### Immutable v4.1 experiment notebook

`notebooks/16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb`

This notebook preserves the historical v4.1 architecture, buy/sell signals, event study and long-history attack-layer analysis. It must not be silently rewritten using later information.

### Rolling current-strategy notebook

`notebooks/17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb`

This notebook must identify v4.2 as the current research baseline and v4.1 as the immutable historical comparator. It must continue to show metrics, equity, drawdown, state-path equality, signal-versus-execution timing, executed asset trades and prospective observations.

### v4.2 experiment-suite notebook

`notebooks/18_qqqi_qqq_tqqq_v4_2_baseline_experiment_suite.ipynb`

This notebook records:

- actual state-1 lifecycle attribution;
- expected shortfall and drawdown-duration diagnostics;
- pure-SGOV and blended QQQI/SGOV defensive challengers;
- chronological stability;
- equity and drawdown comparisons;
- the unchanged 10 bps cost convention.

It must be re-executed whenever the v4.2 diagnostic or SGOV experiment implementation changes.

## Saving experimental results

For every completed experiment:

1. upload full evidence through the experiment workflow;
2. record workflow run, artifact ID and SHA-256 digest in the result report or ledger;
3. add the experiment decision to the ledger;
4. save primary metrics and evidence identifiers in a compact JSON snapshot;
5. update the applicable rolling or experiment notebook;
6. keep rejected hypotheses in the ledger so they are not repeatedly rediscovered and retested.

The current canonical compact snapshot is:

`docs/research/snapshots/qqqi_vxn_v4_1_v4_2_2026-07-31.json`

## Alert policy

The v4.2 signal-alert layer must consume the latest v4.2 prospective-monitor summary. It may not independently recreate the signal state machine.

An alert is valid only when:

- latest close-derived decision state differs from the latest executed position state;
- target asset weights change;
- signal date and intended next-open execution are shown separately;
- the message includes a deterministic deduplication fingerprint;
- the message states that it is research-only and does not place an order.

GitHub Issue is the canonical durable alert channel. Telegram is optional and must use the same rendered payload. Re-running a workflow must not create a duplicate issue for the same fingerprint.

## Notebook refresh procedure

Run from the repository root:

```bash
uv sync --frozen --extra dev
uv run python scripts/refresh_qqqi_vxn_current_notebook.py
uv run python scripts/promote_qqqi_v4_2_notebook_roles.py
```

The refresh process must:

- execute applicable notebooks from a clean kernel;
- fail on any notebook error;
- preserve generated tables and figures in the committed `.ipynb`;
- stamp stable snapshot and contract hashes where applicable;
- avoid volatile metadata that creates meaningless diffs;
- leave the immutable v4.1 notebook unchanged except for documented calculation corrections.

## Pull-request completion rule

A pull request that changes any of the following must update or explicitly confirm the applicable notebook and ledger:

- `configs/research_paradigms/qqqi_qqq_tqqq_*`;
- `src/research/vxn_*`, `src/research/v4_2_*` or signal-alert code;
- `scripts/run_qqqi_*`;
- current-baseline designation;
- experiment ledger or durable snapshots.

A non-economic formatting or test-only change may leave notebook output unchanged only when the PR description says why.

## Current status

- v4.2 is the current research baseline from 2026-08-02;
- v4.1 is the historical signal comparator;
- prospective boundary remains 2026-08-01;
- state-1 lifecycle, tail-risk and SGOV defensive experiments are the active next research sequence;
- no additional retrospective factor, threshold or bridge-weight search is permitted on the same sample;
- no strategy is trade-ready.
