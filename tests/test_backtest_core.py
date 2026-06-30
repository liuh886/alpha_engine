"""Tests for src/research/backtest_core.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.backtest_core import (
    BacktestSummary,
    build_backtest_summary,
    compute_portfolio_returns,
    compute_turnover,
    max_drawdown,
    select_topn_no_guardrail,
    select_topn_with_guardrail,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def five_stock_scores():
    return pd.Series({"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3, "E": 0.1})


@pytest.fixture
def five_stock_prices():
    return pd.Series({"A": 150.0, "B": 80.0, "C": 50.0, "D": 20.0, "E": 10.0})


@pytest.fixture
def five_stock_ma60():
    # A and B above MA60; C, D, E below
    return pd.Series({"A": 140.0, "B": 75.0, "C": 55.0, "D": 25.0, "E": 12.0})


# ---------------------------------------------------------------------------
# select_topn_with_guardrail
# ---------------------------------------------------------------------------

def test_select_topn_returns_at_most_topk(five_stock_scores):
    result = select_topn_with_guardrail(five_stock_scores, topk=3)
    assert len(result) <= 3


def test_select_topn_filters_score_lte_zero():
    scores = pd.Series({"A": 0.5, "B": 0.0, "C": -0.1})
    result = select_topn_with_guardrail(scores, topk=3)
    assert "B" not in result
    assert "C" not in result


def test_select_topn_guardrail_price_above_ma60(
    five_stock_scores, five_stock_prices, five_stock_ma60
):
    # Only A and B have price > MA60
    result = select_topn_with_guardrail(
        five_stock_scores, topk=5, prices=five_stock_prices, ma60=five_stock_ma60
    )
    assert set(result) == {"A", "B"}


def test_select_topn_no_guardrail_skips_price_filter(five_stock_scores):
    # No price/ma60 passed — only score > 0 filter applies
    result = select_topn_with_guardrail(five_stock_scores, topk=5)
    assert len(result) == 5


def test_select_topn_no_guardrail_returns_bottom_k(five_stock_scores):
    result = select_topn_no_guardrail(five_stock_scores, topk=2)
    assert set(result) == {"D", "E"}


# ---------------------------------------------------------------------------
# compute_portfolio_returns
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_backtest_inputs():
    dates = pd.bdate_range("2024-01-02", periods=10)
    tickers = ["A", "B", "C"]
    rng = np.random.default_rng(0)
    daily_rets = pd.DataFrame(
        rng.normal(0.001, 0.01, (len(dates), len(tickers))),
        index=dates, columns=tickers
    )
    bench_ret = pd.Series(rng.normal(0.0005, 0.008, len(dates)), index=dates)
    holdings = {d: ["A", "B"] for d in dates}
    return holdings, daily_rets, bench_ret


def test_compute_portfolio_returns_shape(simple_backtest_inputs):
    holdings, daily_rets, bench_ret = simple_backtest_inputs
    hist_df = compute_portfolio_returns(holdings, daily_rets, bench_ret)
    assert len(hist_df) == len(holdings)
    assert "portfolio_value" in hist_df.columns
    assert "excess_alpha" in hist_df.columns


def test_portfolio_value_positive(simple_backtest_inputs):
    holdings, daily_rets, bench_ret = simple_backtest_inputs
    hist_df = compute_portfolio_returns(holdings, daily_rets, bench_ret)
    assert (hist_df["portfolio_value"] > 0).all()


def test_no_holdings_zero_pnl(simple_backtest_inputs):
    _, daily_rets, bench_ret = simple_backtest_inputs
    empty_holdings = {d: [] for d in daily_rets.index}
    hist_df = compute_portfolio_returns(empty_holdings, daily_rets, bench_ret)
    # With no holdings daily_return should always be 0
    assert (hist_df["daily_return"] == 0.0).all()


# ---------------------------------------------------------------------------
# compute_turnover
# ---------------------------------------------------------------------------

def test_turnover_zero_when_unchanged():
    dates = pd.bdate_range("2024-01-02", periods=5)
    holdings = {d: ["A", "B"] for d in dates}
    t = compute_turnover(holdings)
    assert (t.dropna() == 0.0).all()


def test_turnover_one_when_fully_replaced():
    dates = pd.bdate_range("2024-01-02", periods=2)
    holdings = {dates[0]: ["A", "B"], dates[1]: ["C", "D"]}
    t = compute_turnover(holdings)
    assert t.iloc[1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

def test_max_drawdown_monotone_up():
    eq = pd.Series([1.0, 1.1, 1.2, 1.3])
    assert max_drawdown(eq) == pytest.approx(0.0)


def test_max_drawdown_known_value():
    eq = pd.Series([1.0, 1.2, 0.9, 1.1])
    # Peak at 1.2, trough at 0.9 → 0.9/1.2 - 1 = -0.25
    assert max_drawdown(eq) == pytest.approx(-0.25)


# ---------------------------------------------------------------------------
# build_backtest_summary
# ---------------------------------------------------------------------------

def test_build_backtest_summary_returns_dataclass(simple_backtest_inputs):
    holdings, daily_rets, bench_ret = simple_backtest_inputs
    hist_df = compute_portfolio_returns(holdings, daily_rets, bench_ret)
    summary = build_backtest_summary(hist_df, bench_ret)
    assert isinstance(summary, BacktestSummary)
    assert -1.0 < summary.total_return < 10.0  # sanity
    assert summary.max_drawdown <= 0.0
