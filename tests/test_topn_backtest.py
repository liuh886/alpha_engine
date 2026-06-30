"""Tests for TopN rolling backtest engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.topn_backtest import (
    build_daily_sleeves,
    compute_turnover,
    run_topn_rolling_backtest,
    select_top_n,
)


def _sample_signal_and_returns():
    dates = pd.bdate_range("2024-01-02", periods=15)
    tickers = ["A", "B", "C", "D", "E"]

    signal_rows = []
    for d in dates:
        for i, t in enumerate(tickers):
            signal_rows.append({"date": d, "ticker": t, "winner_prob": 1.0 - i * 0.1})
    signal_df = pd.DataFrame(signal_rows)

    # Make A/B consistently stronger than others
    realized = pd.DataFrame(
        {
            "A": np.full(len(dates), 0.010),
            "B": np.full(len(dates), 0.008),
            "C": np.full(len(dates), 0.002),
            "D": np.full(len(dates), -0.001),
            "E": np.full(len(dates), -0.003),
        },
        index=dates,
    )
    bench = pd.Series(np.full(len(dates), 0.001), index=dates, name="bench")
    return signal_df, realized, bench


def test_select_top_n_returns_expected_count():
    signal_df, _, _ = _sample_signal_and_returns()
    selected = select_top_n(signal_df, score_col="winner_prob", top_n=2)
    per_date = selected.groupby("date")["ticker"].nunique()
    assert (per_date == 2).all()


def test_build_daily_sleeves_expands_holding_window():
    signal_df, _, _ = _sample_signal_and_returns()
    selected = select_top_n(signal_df, score_col="winner_prob", top_n=1).head(1)
    sleeves = build_daily_sleeves(selected[["date", "ticker"]], holding_days=5)
    assert len(sleeves) == 5
    assert sleeves["sleeve_age"].tolist() == [0, 1, 2, 3, 4]


def test_compute_turnover_zero_when_basket_same():
    signal_df, _, _ = _sample_signal_and_returns()
    selected = select_top_n(signal_df, score_col="winner_prob", top_n=2)
    turnover = compute_turnover(selected)
    assert (turnover.dropna() == 0.0).all()


def test_run_topn_rolling_backtest_positive_alpha():
    signal_df, realized, bench = _sample_signal_and_returns()
    portfolio_df, summary = run_topn_rolling_backtest(
        signal_df=signal_df,
        realized_returns=realized,
        bench_returns=bench,
        score_col="winner_prob",
        top_n=2,
        holding_days=5,
    )
    assert "portfolio_return" in portfolio_df.columns
    assert "excess_alpha" in portfolio_df.columns
    assert summary.mean_daily_alpha > 0
    assert summary.annualized_alpha > 0
    assert summary.mean_daily_spread is not None
    assert summary.mean_daily_spread > 0
