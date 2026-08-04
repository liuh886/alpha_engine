"""Performance guard for the canonical dense-array research backtest."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from src.research.vectorized_backtest import run_vectorized_backtest


def test_cn130_five_year_array_backtest_stays_interactive() -> None:
    rng = np.random.default_rng(20260805)
    dates = pd.bdate_range("2021-01-04", periods=1_400)
    instruments = [f"{600000 + index:06d}" for index in range(130)]
    index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    predictions = pd.DataFrame({"score": rng.normal(size=len(index))}, index=index)
    returns = pd.DataFrame({"return": rng.normal(0.0002, 0.012, size=len(index))}, index=index)
    predictions.loc[rng.random(len(index)) < 0.02, "score"] = np.nan
    returns.loc[rng.random(len(index)) < 0.01, "return"] = np.nan

    started = time.perf_counter()
    result = run_vectorized_backtest(
        predictions,
        returns,
        topk=15,
        rebalance_days=10,
        cost_bps=20.0,
        non_overlapping=True,
    )
    elapsed = time.perf_counter() - started

    assert result.n_periods == 140
    assert elapsed < 1.0, f"CN130 five-year array backtest took {elapsed:.3f}s"
