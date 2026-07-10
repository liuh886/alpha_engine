"""Parity tests for explicit SignalFrame and PortfolioIntent semantics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.portfolio_intent import (
    SignalFrame,
    evaluate_portfolio_intent,
    run_score_backtest_via_intent,
    score_to_equal_weight_intent,
)
from src.research.vectorized_backtest import run_vectorized_backtest


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(9601)
    dates = pd.bdate_range("2025-01-02", periods=45)
    symbols = [f"SH{600000 + index:06d}" for index in range(20)]
    index = pd.MultiIndex.from_product(
        [dates, symbols], names=["datetime", "instrument"]
    )
    scores = rng.normal(size=len(index))
    predictions = pd.DataFrame({"score": scores}, index=index)
    returns = pd.DataFrame(
        {"return": scores * 0.01 + rng.normal(scale=0.005, size=len(index))},
        index=index,
    )
    benchmark = pd.DataFrame(
        {"return": rng.normal(loc=0.0002, scale=0.004, size=len(dates))},
        index=dates,
    )
    return predictions, returns, benchmark


def _assert_legacy_parity(legacy, explicit) -> None:
    scalar_fields = (
        "total_return",
        "benchmark_return",
        "excess_return",
        "max_drawdown",
        "sharpe_ratio",
        "annual_return",
        "volatility",
        "mean_ic",
        "ic_ir",
        "positive_ic_ratio",
        "turnover",
        "costs",
        "net_return",
        "information_ratio",
    )
    for field in scalar_fields:
        assert getattr(explicit, field) == pytest.approx(
            getattr(legacy, field), rel=1e-12, abs=1e-12
        ), field
    np.testing.assert_allclose(
        explicit.portfolio_values,
        legacy.portfolio_values,
        rtol=1e-12,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        explicit.benchmark_values,
        legacy.benchmark_values,
        rtol=1e-12,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        explicit.daily_returns,
        legacy.daily_returns,
        rtol=1e-12,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        explicit.ic_series,
        legacy.ic_series,
        rtol=1e-12,
        atol=1e-12,
    )
    assert explicit.topk == legacy.topk
    assert explicit.rebalance_days == legacy.rebalance_days
    assert explicit.n_periods == legacy.n_periods
    assert explicit.test_start == legacy.test_start
    assert explicit.test_end == legacy.test_end


def test_explicit_intent_matches_legacy_non_overlapping_backtest() -> None:
    predictions, returns, benchmark = _fixture()
    legacy = run_vectorized_backtest(
        predictions,
        returns,
        benchmark_returns=benchmark,
        topk=5,
        rebalance_days=10,
        initial_capital=100_000.0,
        cost_bps=12.0,
        non_overlapping=True,
    )
    explicit = run_score_backtest_via_intent(
        predictions,
        returns,
        benchmark_returns=benchmark,
        top_n=5,
        rebalance_days=10,
        initial_capital=100_000.0,
        cost_bps=12.0,
    )
    _assert_legacy_parity(legacy, explicit)


def test_intent_preserves_legacy_hold_on_missing_rebalance_scores() -> None:
    predictions, returns, benchmark = _fixture()
    dates = sorted(predictions.index.get_level_values("datetime").unique())
    predictions = predictions.drop(index=dates[10], level="datetime")

    legacy = run_vectorized_backtest(
        predictions,
        returns,
        benchmark_returns=benchmark,
        topk=4,
        rebalance_days=10,
        cost_bps=20.0,
        non_overlapping=True,
    )
    explicit = run_score_backtest_via_intent(
        predictions,
        returns,
        benchmark_returns=benchmark,
        top_n=4,
        rebalance_days=10,
        cost_bps=20.0,
    )
    _assert_legacy_parity(legacy, explicit)


def test_portfolio_intent_contains_explicit_equal_weights() -> None:
    predictions, returns, _ = _fixture()
    common_dates = tuple(
        sorted(
            set(predictions.index.get_level_values("datetime"))
            & set(returns.index.get_level_values("datetime"))
        )
    )
    signal = SignalFrame(
        scores=predictions,
        research_contract_id="contract-fixture",
        strategy_id="top5-equal-weight",
        benchmark="000300",
        rebalance_days=10,
    )
    intent = score_to_equal_weight_intent(
        signal,
        top_n=5,
        evaluation_dates=common_dates,
    )
    report = evaluate_portfolio_intent(intent, returns, cost_bps=0.0)

    assert intent.research_contract_id == "contract-fixture"
    assert intent.strategy_id == "top5-equal-weight"
    assert intent.constraints == {"long_only": True, "fully_invested": True}
    totals = intent.target_weights["target_weight"].groupby(level="datetime").sum()
    np.testing.assert_allclose(totals.to_numpy(), 1.0, rtol=0.0, atol=1e-12)
    assert set(intent.target_weights["target_weight"].unique()) == {0.2}
    assert report.n_periods == len(intent.rebalance_dates)


def test_raw_10d_provenance_gate_is_preserved() -> None:
    predictions, returns, _ = _fixture()
    with pytest.raises(ValueError, match="raw_forward_return"):
        run_score_backtest_via_intent(
            predictions,
            returns,
            top_n=5,
            require_raw_10d_returns=True,
        )

    returns.attrs.update({"provenance": "raw_forward_return", "horizon": 10})
    result = run_score_backtest_via_intent(
        predictions,
        returns,
        top_n=5,
        require_raw_10d_returns=True,
    )
    assert result.n_periods > 0
