# Research notebooks

The QQQI / QQQ / TQQQ research line uses two notebook roles.

## Historical experiment snapshots

Historical experiment notebooks preserve what was known at the time of the experiment. They should not be silently rewritten after a later hypothesis is created.

Current historical snapshot:

- `16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb` — complete v4.1 backtest, buy/sell points, event study and long-history attack-layer context.

## Rolling current-strategy review

- `17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb`

This notebook is the current human-readable comparison of:

- QQQ buy and hold;
- frozen v4.1 baseline;
- v4.2 50/50 bridge challenger;
- prospective evidence dated on or after 2026-08-01.

It must be refreshed whenever the active baseline, challenger, canonical result snapshot or prospective review changes.

Run from the repository root:

```bash
uv sync --frozen --extra dev
uv run python scripts/refresh_qqqi_vxn_current_notebook.py
uv run python scripts/validate_qqqi_vxn_research_bundle.py --require-executed
```

The scheduled notebook-refresh workflow executes the rolling notebook weekly and opens or updates a pull request when the saved outputs change.

The full governance and result-storage policy is documented in:

`docs/research/qqqi_vxn_research_result_and_notebook_policy.md`
