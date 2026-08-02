# Research notebooks

The QQQI / QQQ / TQQQ research line uses historical, rolling and governed diagnostic notebook roles.

## Historical experiment snapshots

Historical experiment notebooks preserve what was known at the time of the experiment. They should not be silently rewritten after a later hypothesis is created.

Current historical snapshot:

- `16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb` — complete v4.1 backtest, buy/sell points, event study and long-history attack-layer context.

## Rolling current-strategy review

- `17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb`

This notebook is the current human-readable comparison of:

- QQQ buy and hold;
- historical v4.1 signal comparator;
- current v4.2 50/50 bridge research baseline;
- prospective evidence dated on or after 2026-08-01.

It must be refreshed whenever the active baseline, canonical result snapshot or prospective review changes.

## Governed diagnostic notebooks

- `18_qqqi_qqq_tqqq_v4_2_baseline_experiment_suite.ipynb` — state-1 lifecycle, tail-risk and frozen SGOV defensive-asset studies.
- `19_qqqi_qqq_tqqq_v4_2_state2_tail_diagnostics.ipynb` — state-2 episodes, intraday/overnight loss decomposition and execution/cost robustness.
- `20_qqqi_qqq_tqqq_v4_2_risk_confirmation_ablation.ipynb` — corrected distinction between mechanical delay and one-session confirmation on `0→1`, `1→2` and combined risk-increasing transitions.
- `21_qqqi_qqq_tqqq_v4_2_sgov_episode_attribution.ipynb` — drawdown-depth, recovery-duration and phase/state attribution for the frozen 50% QQQI / 50% SGOV defensive profile.

Notebooks 19 and 20 record a completed research decision:

- v4.2 remains unchanged as the current research baseline;
- close-based continuous state-2 volatility scaling is rejected;
- bridge-entry confirmation is rejected;
- leverage-entry confirmation is not promoted because the result is chronologically unstable and has a low event win rate;
- no additional retrospective confirmation, persistence or threshold search is authorized on the current sample.

Notebook 21 is a monitor-admission study, not a weight search. It explains whether the already frozen blended defensive profile improves major drawdown episodes consistently enough, and with a sufficiently small recovery penalty, to justify a separate prospective research monitor. Passing never replaces v4.2.

Run the rolling notebook from the repository root:

```bash
uv sync --frozen --extra dev
uv run python scripts/refresh_qqqi_vxn_current_notebook.py
uv run python scripts/validate_qqqi_vxn_research_bundle.py --require-executed
```

The scheduled notebook-refresh workflow executes the rolling notebook weekly and opens or updates a pull request when the saved outputs change. Diagnostic notebooks are executed by their evidence workflows; workflow artifacts preserve the executed copy without repeatedly rewriting the branch.

The full governance and result-storage policy is documented in:

`docs/research/qqqi_vxn_research_result_and_notebook_policy.md`
