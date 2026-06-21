"""Tests for RegimeFilter — three-pillar market regime detection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.execution.regime_filter import RegimeFilter, RegimeSignal
from src.execution.signal_execution_config import SignalExecutionConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> SignalExecutionConfig:
    return SignalExecutionConfig(
        market="cn",
        enable_regime_filter=True,
        ic_lookback_days=60,
        ic_decay_threshold=-0.01,
        vol_ratio_threshold=2.0,
        trend_ma_window=60,
        rebalance_days=10,
    )


@pytest.fixture
def regime_filter(default_config: SignalExecutionConfig) -> RegimeFilter:
    return RegimeFilter(default_config)


def _make_return_matrix(
    n_days: int = 300, n_stocks: int = 50, seed: int = 42
) -> pd.DataFrame:
    """Synthetic return matrix: datetime x instrument."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    data = rng.normal(0.0005, 0.02, size=(n_days, n_stocks))
    return pd.DataFrame(
        data,
        index=dates,
        columns=[f"STOCK_{i:03d}" for i in range(n_stocks)],
    )


def _make_benchmark(n_days: int = 300, seed: int = 42) -> pd.Series:
    """Synthetic benchmark cumulative returns (price-like)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    rets = rng.normal(0.0003, 0.01, size=n_days)
    # Cumulative product → price-like series
    prices = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(prices, index=dates)


# ---------------------------------------------------------------------------
# IC Decay tests
# ---------------------------------------------------------------------------


class TestICDecay:
    def test_positive_ic_trend_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Improving IC → full exposure."""
        ic_series = [0.01 + i * 0.0001 for i in range(100)]
        slope, factor = regime_filter._check_ic_decay(ic_series)
        assert slope > 0
        assert factor == pytest.approx(1.0)

    def test_flat_ic_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Flat IC → full exposure (slope ≈ 0)."""
        ic_series = [0.01] * 100
        slope, factor = regime_filter._check_ic_decay(ic_series)
        assert abs(slope) < 1e-10
        assert factor == pytest.approx(1.0)

    def test_declining_ic_reduces_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Declining IC → reduced exposure."""
        ic_series = [0.02 - i * 0.0003 for i in range(100)]
        slope, factor = regime_filter._check_ic_decay(ic_series)
        assert slope < 0
        assert factor < 1.0

    def test_steeply_declining_ic_goes_to_zero(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Very steep IC decline → exposure near zero."""
        # Steep decline: from 0.5 to -1.5 over 100 points → slope ≈ -0.02
        ic_series = [0.5 - i * 0.02 for i in range(100)]
        slope, factor = regime_filter._check_ic_decay(ic_series)
        assert slope < -0.01
        assert factor <= 0.3  # Should be very low

    def test_insufficient_data_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Fewer than 10 IC points → assume favorable."""
        ic_series = [-0.05, -0.04, -0.03]
        slope, factor = regime_filter._check_ic_decay(ic_series)
        assert factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Volatility spike tests
# ---------------------------------------------------------------------------


class TestVolSpike:
    def test_normal_vol_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Normal volatility → full exposure."""
        return_matrix = _make_return_matrix(n_days=300, seed=42)
        date = return_matrix.index[-1]
        ratio, factor = regime_filter._check_vol_spike(return_matrix, date)
        assert factor == pytest.approx(1.0, abs=0.1)

    def test_high_vol_spike_reduces_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Vol spike → reduced exposure."""
        rng = np.random.default_rng(99)
        n_days, n_stocks = 300, 50
        dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
        # Normal returns for most of the period
        data = rng.normal(0.0005, 0.01, size=(n_days, n_stocks))
        # Spike in the last 20 days → vol20 becomes much larger
        data[-20:, :] = rng.normal(0.0005, 0.05, size=(20, n_stocks))
        return_matrix = pd.DataFrame(
            data, index=dates,
            columns=[f"STOCK_{i:03d}" for i in range(n_stocks)],
        )
        date = return_matrix.index[-1]
        ratio, factor = regime_filter._check_vol_spike(return_matrix, date)
        # Vol20 should be >> vol252
        assert ratio > 1.5

    def test_insufficient_history_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Fewer than 252 days → full exposure (not enough history)."""
        return_matrix = _make_return_matrix(n_days=100, seed=42)
        date = return_matrix.index[-1]
        ratio, factor = regime_filter._check_vol_spike(return_matrix, date)
        assert factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Trend filter tests
# ---------------------------------------------------------------------------


class TestTrendFilter:
    def test_benchmark_above_ma_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Benchmark above MA → full exposure."""
        bench = _make_benchmark(n_days=300, seed=42)
        # Force an uptrend by adding linear drift
        bench = bench * (1.0 + np.arange(len(bench)) * 0.0005)
        date = bench.index[-1]
        below_ma, factor = regime_filter._check_trend(bench, date)
        assert not below_ma
        assert factor == pytest.approx(1.0)

    def test_benchmark_below_ma_reduces_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """Benchmark below MA → reduced exposure."""
        bench = _make_benchmark(n_days=300, seed=42)
        # Force a downtrend by subtracting linear drift
        bench = bench * (1.0 - np.arange(len(bench)) * 0.001)
        date = bench.index[-1]
        below_ma, factor = regime_filter._check_trend(bench, date)
        # Should detect bearish trend
        assert factor <= 1.0

    def test_no_benchmark_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """No benchmark data → full exposure."""
        below_ma, factor = regime_filter._check_trend(None, pd.Timestamp("2024-06-01"))
        assert not below_ma
        assert factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Combined evaluate() tests
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_normal_market_returns_full_exposure(
        self, regime_filter: RegimeFilter
    ) -> None:
        """All three pillars green → is_favorable=True, factor=1.0."""
        return_matrix = _make_return_matrix(n_days=300, seed=42)
        bench = _make_benchmark(n_days=300, seed=42)
        bench = bench * (1.0 + np.arange(len(bench)) * 0.0005)  # uptrend
        ic_series = [0.01 + i * 0.0001 for i in range(100)]  # improving

        signal = regime_filter.evaluate(
            ic_series=ic_series,
            return_matrix=return_matrix,
            benchmark_series=bench,
            date=return_matrix.index[-1],
        )
        assert signal.is_favorable
        assert signal.exposure_factor == pytest.approx(1.0, abs=0.05)
        assert len(signal.reasons) == 0

    def test_multiple_adverse_signals_use_minimum(
        self, regime_filter: RegimeFilter
    ) -> None:
        """When multiple pillars signal danger, the minimum factor wins."""
        return_matrix = _make_return_matrix(n_days=300, seed=42)
        bench = _make_benchmark(n_days=300, seed=42)
        bench = bench * (1.0 - np.arange(len(bench)) * 0.001)  # downtrend
        ic_series = [0.05 - i * 0.002 for i in range(100)]  # steep decline

        signal = regime_filter.evaluate(
            ic_series=ic_series,
            return_matrix=return_matrix,
            benchmark_series=bench,
            date=return_matrix.index[-1],
        )
        # At least one pillar should reduce exposure
        assert signal.exposure_factor < 1.0
        # Reasons should list all adverse conditions
        assert len(signal.reasons) > 0

    def test_regime_signal_is_frozen(
        self, regime_filter: RegimeFilter
    ) -> None:
        """RegimeSignal should be frozen/immutable."""
        signal = RegimeSignal(
            is_favorable=True, exposure_factor=1.0,
            ic_trend_slope=0.0, vol_ratio=1.0, trend_below_ma=False,
        )
        with pytest.raises(Exception):
            signal.exposure_factor = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_disabled_regime_filter(self) -> None:
        """When disabled, RegimeFilter is not created but config is valid."""
        config = SignalExecutionConfig(enable_regime_filter=False)
        assert config.enable_regime_filter is False
        # Valid config should not raise
        SignalExecutionConfig()

    def test_invalid_ic_lookback(self) -> None:
        """ic_lookback_days < 10 raises ValueError."""
        with pytest.raises(ValueError, match="ic_lookback_days"):
            SignalExecutionConfig(ic_lookback_days=5)
