from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_factor_discovery_v2 import (
    FORWARD_RETURN_COLUMN,
    build_factor_dataset,
    discover_factors,
    factor_diagnostics,
)


def _bars(periods: int = 1800) -> pd.DataFrame:
    index = pd.bdate_range("2011-01-03", periods=periods)
    rng = np.random.default_rng(506)
    regime = np.where((np.arange(periods) // 160) % 2 == 0, 0.0008, -0.0003)
    returns = regime + rng.normal(0.0, 0.018, periods)
    close = 25.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.003, periods))
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.001, 0.015, periods))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.001, 0.015, periods))
    return pd.DataFrame(
        {
            "date": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 20_000_000, periods),
        }
    )


def test_forward_label_starts_at_next_open_and_ends_ten_sessions_later() -> None:
    bars = _bars(700)
    dataset, _ = build_factor_dataset(bars)
    position = 300
    expected = dataset["open"].iloc[position + 11] / dataset["open"].iloc[position + 1] - 1.0
    assert np.isclose(dataset[FORWARD_RETURN_COLUMN].iloc[position], expected)


def test_future_mutation_does_not_change_prior_features() -> None:
    bars = _bars(900)
    dataset_a, factors_a = build_factor_dataset(bars)
    changed = bars.copy()
    changed.loc[changed.index >= 820, ["open", "high", "low", "close", "volume"]] *= 1.5
    dataset_b, factors_b = build_factor_dataset(changed)
    assert factors_a == factors_b
    cutoff = dataset_a.index[819]
    pd.testing.assert_frame_equal(
        dataset_a.loc[:cutoff, factors_a],
        dataset_b.loc[:cutoff, factors_b],
    )


def test_factor_library_contains_recovery_and_state_interactions() -> None:
    _, factors = build_factor_dataset(_bars(800))
    expected = {
        "drawdown_120",
        "drawdown_252",
        "distance_from_low_20",
        "distance_from_low_60",
        "drawdown120_x_rebound20",
        "drawdown252_x_rebound60",
        "recovery_velocity_20_60",
        "short_continuation_long_reversal",
        "vol_compression_20_60",
        "rebound_volume_confirmation",
    }
    assert expected.issubset(factors)


def test_diagnostics_are_period_stability_based() -> None:
    dataset, factors = build_factor_dataset(_bars(1800))
    diagnostics = factor_diagnostics(dataset, factors[:8])
    assert len(diagnostics) == 8
    assert diagnostics["period_sign_consistency"].between(0.0, 1.0).all()
    assert {
        "median_oriented_ic",
        "worst_oriented_ic",
        "stability_score",
    }.issubset(diagnostics.columns)


def test_discovery_is_exploratory_and_returns_correlation_matrix() -> None:
    result = discover_factors(_bars(1800))
    assert not result.diagnostics.empty
    assert result.correlation.shape[0] == result.correlation.shape[1]
    assert set(result.shortlist.columns).issubset(result.diagnostics.columns)
