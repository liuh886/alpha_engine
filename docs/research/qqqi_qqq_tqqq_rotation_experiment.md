# QQQI / QQQ / TQQQ Rotation Experiment

This experiment is a separate, research-only diagnostic path. It does not
replace AlphaEngine's currently active minimal US fundamental validation and it
does not authorize trading.

## Research questions

1. Does QQQI deliver lower drawdown and volatility than QQQ when QQQ is below
   its 200-day moving average or in an above-MA200 sideways regime?
2. After QQQ crosses back above MA200, does QQQ recover faster than QQQI over
   the next 20 sessions?
3. Does a close-signal / next-open state machine rotating among QQQI, QQQ and
   TQQQ improve CAGR, maximum drawdown, Sharpe, Sortino and Calmar relative to
   common-window buy-and-hold baselines?
4. Are those results stable across a declared parameter neighborhood?

## Critical sample limitation

QQQI's official fund inception date is 2024-01-29, as reported on the
[NEOS official fund page](https://neosfunds.com/qqqi/). Therefore the three-asset
strategy cannot be tested directly through the 2020 pandemic crash or the 2022
rate-hike bear market. The implementation fails closed on common tradable
history and labels pre-inception named periods as insufficient rather than
backfilling QQQI or silently substituting a proxy.

QQQ and TQQQ may still be inspected over their longer histories for context,
but those observations are not evidence for the QQQI state.

## Execution contract

- All indicators use QQQ observations available at session close `t`.
- The desired state is decided after close `t`.
- The position changes at the next session open `t+1`.
- Economic return is measured adjusted-open to adjusted-open.
- A state switch incurs two transaction-cost legs; the initial entry incurs one.
- QQQI, QQQ and TQQQ are compared over the same common sessions.

This differs from the tempting but invalid pattern of using close `t` to select
an asset and also earning that asset's close-to-close return for `t`.

## Files

- Frozen contract: `configs/research_paradigms/qqqi_qqq_tqqq_rotation_v1.yaml`
- Reusable engine: `src/research/etf_rotation_experiment.py`
- CLI: `scripts/run_qqqi_qqq_tqqq_rotation.py`
- Notebook: `notebooks/12_qqqi_qqq_tqqq_rotation.ipynb`
- Tests: `tests/test_etf_rotation_experiment.py`

## Run

```bash
uv run python scripts/run_qqqi_qqq_tqqq_rotation.py
```

To inspect interactively:

```bash
uv run jupyter lab notebooks/12_qqqi_qqq_tqqq_rotation.ipynb
```

The CLI writes source coverage, strategy metrics, daily traces, trades,
conditional regime comparisons, recovery events, named-period coverage,
chronological split results, the full sensitivity grid and an evidence manifest
under `artifacts/evidence/qqqi_qqq_tqqq_rotation_v1/`.

## Interpretation discipline

The default parameter set is the primary test. The grid is a robustness
inspection only. A high-Calmar combination found after looking at outcomes must
not be presented as validated without a new frozen contract and genuinely new
out-of-sample data.
