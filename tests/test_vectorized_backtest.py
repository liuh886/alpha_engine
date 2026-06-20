"""Tests for the vectorized backtest engine."""

import numpy as np
import pandas as pd

from src.research.vectorized_backtest import (
    AdapterBacktestConfig,
    BacktestResult,
    benchmark_adapter_paths,
    compute_ic_vectorized,
    run_ordinary_adapter_backtest,
    run_vectorized_adapter_backtest,
    run_vectorized_backtest,
)
from src.strategies.vectorized_engine import VectorizedSignalPrecomputer
from src.strategies.vectorized_strategy import VectorizedBiweeklyStrategy


def _make_predictions(n_dates=30, n_stocks=50, seed=42):
    """Create synthetic predictions."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    stocks = [f"stock_{i:03d}" for i in range(n_stocks)]

    idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
    scores = rng.randn(len(idx))
    return pd.DataFrame({"score": scores}, index=idx)


def _make_returns(predictions, noise_std=0.1, seed=42):
    """Create synthetic returns correlated with predictions."""
    rng = np.random.RandomState(seed)
    returns = predictions.copy()
    returns.columns = ["return"]
    # Add noise to make it realistic
    returns["return"] = predictions["score"] * 0.3 + rng.randn(len(predictions)) * noise_std
    return returns


class TestComputeICVectorized:
    """Tests for IC computation."""

    def test_perfect_correlation(self):
        """Perfect correlation should give IC ≈ 1.0."""
        pred = _make_predictions(n_dates=20, n_stocks=30)
        # Returns = predictions (perfect correlation)
        returns = pred.copy()
        returns.columns = ["return"]

        mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(pred, returns)
        assert mean_ic > 0.99
        assert len(ic_series) > 0

    def test_no_correlation(self):
        """Random predictions and returns should give IC ≈ 0."""
        pred = _make_predictions(n_dates=50, n_stocks=50, seed=42)
        returns = _make_returns(pred, noise_std=10.0, seed=99)  # Very noisy

        mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(pred, returns)
        assert abs(mean_ic) < 0.2  # Should be near 0 with high noise

    def test_insufficient_data(self):
        """Fewer than 10 stocks should return empty."""
        pred = _make_predictions(n_dates=5, n_stocks=5)
        returns = _make_returns(pred)

        mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(pred, returns)
        assert len(ic_series) == 0  # Not enough stocks


class TestRunVectorizedBacktest:
    """Tests for the full backtest."""

    def test_basic_backtest(self):
        """Basic backtest should return valid results."""
        pred = _make_predictions(n_dates=30, n_stocks=50)
        returns = _make_returns(pred)

        result = run_vectorized_backtest(
            predictions=pred,
            returns=returns,
            topk=5,
            rebalance_days=10,
        )

        assert isinstance(result, BacktestResult)
        assert result.n_periods > 0
        assert result.test_start != ""
        assert result.test_end != ""
        assert result.topk == 5
        assert result.rebalance_days == 10

    def test_with_benchmark(self):
        """Backtest with benchmark should compute excess return."""
        pred = _make_predictions(n_dates=30, n_stocks=50)
        returns = _make_returns(pred)

        # Create benchmark returns
        dates = sorted(pred.index.get_level_values("datetime").unique())
        bench = pd.DataFrame(
            {"return": np.random.RandomState(42).randn(len(dates)) * 0.01},
            index=dates,
        )

        result = run_vectorized_backtest(
            predictions=pred,
            returns=returns,
            benchmark_returns=bench,
            topk=5,
            rebalance_days=10,
        )

        assert result.benchmark_return != 0.0
        assert result.excess_return == result.total_return - result.benchmark_return

    def test_non_overlapping_mode(self):
        """Non-overlapping mode should use fewer periods."""
        pred = _make_predictions(n_dates=50, n_stocks=50)
        returns = _make_returns(pred)

        result_overlap = run_vectorized_backtest(
            predictions=pred, returns=returns, topk=5, rebalance_days=10, non_overlapping=False,
        )
        result_non_overlap = run_vectorized_backtest(
            predictions=pred, returns=returns, topk=5, rebalance_days=10, non_overlapping=True,
        )

        # Non-overlapping should have fewer periods
        assert result_non_overlap.n_periods < result_overlap.n_periods

    def test_deterministic(self):
        """Same inputs should produce identical outputs."""
        pred = _make_predictions(n_dates=30, n_stocks=50, seed=42)
        returns = _make_returns(pred, seed=42)

        result1 = run_vectorized_backtest(predictions=pred, returns=returns, topk=5)
        result2 = run_vectorized_backtest(predictions=pred, returns=returns, topk=5)

        assert result1.total_return == result2.total_return
        assert result1.sharpe_ratio == result2.sharpe_ratio
        assert result1.max_drawdown == result2.max_drawdown

    def test_to_dict(self):
        """to_dict should return serializable dict."""
        pred = _make_predictions(n_dates=20, n_stocks=30)
        returns = _make_returns(pred)

        result = run_vectorized_backtest(predictions=pred, returns=returns, topk=5)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "total_return" in d
        assert "sharpe_ratio" in d
        assert "mean_ic" in d
        # Should be JSON serializable
        import json
        json.dumps(d)


def _make_adapter_fixture(market: str):
    dates = pd.bdate_range("2026-01-05", periods=12)
    instruments = (
        ["SH600000", "SH600036", "SZ000001", "SZ000333", "SH600519", "SZ300750"]
        if market == "cn"
        else ["AAPL", "AMZN", "GOOG", "MSFT", "NVDA", "TSLA"]
    )
    index = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    date_no = np.repeat(np.arange(len(dates), dtype=float), len(instruments))
    stock_no = np.tile(np.arange(len(instruments), dtype=float), len(dates))
    predictions = pd.DataFrame(
        {"score": -0.05 - stock_no * 0.1 + date_no * 0.003}, index=index
    )
    returns = pd.DataFrame(
        {"return": (stock_no - 2.5) * 0.001 + (date_no % 3 - 1) * 0.0005},
        index=index,
    )

    # A missing high-ranked candidate must stay absent. Zero-filling would rank it
    # ahead of every negative score on this rebalance date.
    predictions = predictions.drop(index=(dates[0], instruments[0]))
    config = AdapterBacktestConfig(
        calendar=tuple(dates),
        topk=3,
        rebalance_steps=3,
        initial_capital=100_000.0,
        buy_cost_bps=5.0,
        sell_cost_bps=10.0,
    )
    return predictions, returns, config, instruments[0]


def _make_benchmark_fixture():
    rng = np.random.default_rng(4807)
    dates = pd.bdate_range("2025-01-02", periods=260)
    instruments = [f"SH{600000 + i:06d}" for i in range(100)] + [
        f"SZ{1 + i:06d}" for i in range(100)
    ]
    index = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    predictions = pd.DataFrame({"score": rng.normal(size=len(index))}, index=index)
    returns = pd.DataFrame(
        {"return": rng.normal(0.0002, 0.012, size=len(index))}, index=index
    )
    predictions.loc[rng.random(len(index)) < 0.03, "score"] = np.nan
    config = AdapterBacktestConfig(
        calendar=tuple(dates),
        topk=5,
        rebalance_steps=10,
        initial_capital=1_000_000.0,
        buy_cost_bps=5.0,
        sell_cost_bps=10.0,
    )
    return predictions, returns, config


class TestAdapterGoldenEquivalence:
    """Hermetic Qlib-shaped golden corpus for ordinary/vectorized adapters."""

    @staticmethod
    def _assert_equivalent(ordinary, vectorized):
        assert ordinary.orders == vectorized.orders
        assert ordinary.holdings == vectorized.holdings
        np.testing.assert_allclose(ordinary.nav, vectorized.nav, rtol=1e-12, atol=1e-8)
        assert ordinary.metrics.keys() == vectorized.metrics.keys()
        for metric in ordinary.metrics:
            assert np.isclose(
                ordinary.metrics[metric],
                vectorized.metrics[metric],
                rtol=1e-12,
                atol=1e-12,
            ), metric

    def test_frozen_cn_and_us_fixtures_match(self):
        for market in ("cn", "us"):
            predictions, returns, config, _ = _make_adapter_fixture(market)
            ordinary = run_ordinary_adapter_backtest(predictions, returns, config)
            vectorized = run_vectorized_adapter_backtest(predictions, returns, config)
            self._assert_equivalent(ordinary, vectorized)

    def test_missing_predictions_are_excluded_not_zero_filled(self):
        predictions, returns, config, missing_instrument = _make_adapter_fixture("us")

        score_matrix = VectorizedSignalPrecomputer(ma_window=3)._build_score_matrix(
            predictions,
            pd.DatetimeIndex(config.calendar),
            sorted(returns.index.get_level_values("instrument").unique()),
        )
        vectorized = run_vectorized_adapter_backtest(predictions, returns, config)

        assert pd.isna(score_matrix.loc[config.calendar[0], missing_instrument])
        first_date_buys = {
            order.instrument
            for order in vectorized.orders
            if order.date == config.calendar[0] and order.side == "buy"
        }
        assert missing_instrument not in first_date_buys

    def test_all_missing_predictions_hold_existing_portfolio(self):
        predictions, returns, config, _ = _make_adapter_fixture("us")
        missing_date = config.rebalance_dates[1]
        predictions = predictions.drop(index=missing_date, level="datetime")

        ordinary = run_ordinary_adapter_backtest(predictions, returns, config)
        vectorized = run_vectorized_adapter_backtest(predictions, returns, config)

        self._assert_equivalent(ordinary, vectorized)
        assert all(order.date != missing_date for order in vectorized.orders)
        missing_index = config.calendar.index(missing_date)
        assert vectorized.holdings[missing_index] == vectorized.holdings[missing_index - 1]

    def test_offline_cold_warm_benchmark_enforces_fetch_budget(self):
        predictions, returns, config = _make_benchmark_fixture()

        measurements = benchmark_adapter_paths(predictions, returns, config)

        assert measurements["ordinary_cold"].fetch_count == len(config.rebalance_dates)
        assert measurements["vectorized_cold"].fetch_count == 1
        assert measurements["vectorized_warm"].fetch_count == 0
        for measurement in measurements.values():
            assert measurement.wall_seconds < 2.0
            assert 0 < measurement.peak_memory_bytes < 4 * 1024 * 1024
        self._assert_equivalent(
            measurements["ordinary_cold"].result,
            measurements["vectorized_cold"].result,
        )
        self._assert_equivalent(
            measurements["vectorized_cold"].result,
            measurements["vectorized_warm"].result,
        )


class _CalendarStub:
    trade_date = pd.Timestamp("2026-01-06")
    prediction_date = pd.Timestamp("2026-01-05")

    def get_trade_step(self):
        return 0

    def get_step_time(self, trade_step=None, shift=0):
        date = self.prediction_date if shift else self.trade_date
        return date, date


class _MissingPrecomputedStub:
    def __init__(self):
        self.requested_date = None

    def get_scores_on_date(self, date):
        self.requested_date = date
        return pd.Series(dtype=float)


def _uninitialized_vectorized_strategy(precomputed, signal):
    strategy = object.__new__(VectorizedBiweeklyStrategy)
    strategy.level_infra = {"trade_calendar": _CalendarStub()}
    strategy._precomputed = precomputed
    strategy.signal = signal
    return strategy


def test_missing_precomputed_date_does_not_fall_back_to_another_signal_source():
    class FailOnAccess:
        def get_signal(self, **kwargs):
            raise AssertionError("missing precomputed predictions must not fall back")

    strategy = _uninitialized_vectorized_strategy(_MissingPrecomputedStub(), FailOnAccess())

    decision = strategy.generate_trade_decision()

    assert decision.get_decision() == []


def test_precomputed_lookup_uses_ordinary_shifted_prediction_calendar():
    class EmptySignal:
        def get_signal(self, **kwargs):
            return None

    precomputed = _MissingPrecomputedStub()
    strategy = _uninitialized_vectorized_strategy(precomputed, EmptySignal())

    strategy.generate_trade_decision()

    assert precomputed.requested_date == _CalendarStub.prediction_date


def test_precomputed_moving_average_matches_qlib_full_window_warmup():
    closes = pd.DataFrame(
        {"close": [10.0, 11.0, 12.0]},
        index=pd.MultiIndex.from_product(
            [pd.bdate_range("2026-01-05", periods=3), ["AAPL"]],
            names=["datetime", "instrument"],
        ),
    )

    signals = VectorizedSignalPrecomputer(ma_window=3).precompute_from_frame(
        closes,
        pred_df=None,
    )

    assert signals.ma_matrix["AAPL"].iloc[:2].isna().all()
    assert signals.ma_matrix["AAPL"].iloc[2] == 11.0
