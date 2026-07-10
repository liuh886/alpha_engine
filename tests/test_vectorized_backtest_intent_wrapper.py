"""Tests for the legacy score API's PortfolioIntent compatibility boundary."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.vectorized_backtest import run_vectorized_backtest


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(104)
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


def test_non_overlapping_entrypoint_delegates_all_inputs(monkeypatch) -> None:
    predictions, returns, benchmark = _fixture()
    sentinel = object()
    captured: dict[str, object] = {}

    def fake_run(predictions_arg, returns_arg, benchmark_returns=None, **kwargs):
        captured.update(
            {
                "predictions": predictions_arg,
                "returns": returns_arg,
                "benchmark_returns": benchmark_returns,
                **kwargs,
            }
        )
        return sentinel

    monkeypatch.setattr(
        "src.research.portfolio_intent.run_score_backtest_via_intent",
        fake_run,
    )
    result = run_vectorized_backtest(
        predictions,
        returns,
        benchmark_returns=benchmark,
        topk=7,
        rebalance_days=5,
        initial_capital=123_456.0,
        cost_bps=9.0,
        non_overlapping=True,
        require_raw_10d_returns=False,
    )

    assert result is sentinel
    assert captured["predictions"] is predictions
    assert captured["returns"] is returns
    assert captured["benchmark_returns"] is benchmark
    assert captured["top_n"] == 7
    assert captured["rebalance_days"] == 5
    assert captured["initial_capital"] == 123_456.0
    assert captured["cost_bps"] == 9.0
    assert captured["require_raw_10d_returns"] is False


def test_layered_compatibility_path_does_not_call_intent(monkeypatch) -> None:
    predictions, returns, benchmark = _fixture()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("layered compatibility path must not call PortfolioIntent")

    monkeypatch.setattr(
        "src.research.portfolio_intent.run_score_backtest_via_intent",
        fail_if_called,
    )
    result = run_vectorized_backtest(
        predictions,
        returns,
        benchmark_returns=benchmark,
        topk=5,
        rebalance_days=10,
        non_overlapping=False,
    )

    assert result.n_periods > 0
    assert result.rebalance_days == 10
