from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_single_asset_v1 import (
    CANDIDATE_NAMES,
    build_candidate_positions,
    build_features,
    evaluate_research,
    normalise_ohlcv,
    run_backtest,
)


def _synthetic_ohlcv(periods: int = 1200, start: str = "2012-01-02") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=periods)
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0005, 0.018, periods)
    returns[350:430] -= 0.003
    returns[700:760] += 0.002
    close = 25.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.003, periods))
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.001, 0.02, periods))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.001, 0.02, periods))
    return pd.DataFrame(
        {
            "date": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 8_000_000, periods),
        }
    )


def test_normalise_akshare_chinese_columns() -> None:
    raw = _synthetic_ohlcv(300).rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "volume": "成交量",
        }
    )
    daily = normalise_ohlcv(raw)
    assert list(daily.columns) == ["open", "high", "low", "close", "volume"]
    assert daily.index.is_monotonic_increasing
    assert not daily.index.has_duplicates


def test_signal_is_executed_at_next_open() -> None:
    features = build_features(_synthetic_ohlcv(320))
    decision = pd.Series(0.0, index=features.index)
    decision.loc[features.index[200]:] = 1.0
    result = run_backtest(features, decision, cost_bps=20.0, name="lag_test")
    assert result.daily.loc[features.index[200], "position_at_open"] == 0.0
    assert result.daily.loc[features.index[201], "position_at_open"] == 1.0
    assert result.daily.loc[features.index[201], "transaction_cost"] == 0.002


def test_future_mutation_cannot_change_prior_signals() -> None:
    original = _synthetic_ohlcv(700)
    features_a = build_features(original)
    signals_a = build_candidate_positions(features_a)

    changed = original.copy()
    changed.loc[changed.index >= 620, ["open", "high", "low", "close"]] *= 2.0
    features_b = build_features(changed)
    signals_b = build_candidate_positions(features_b)

    cutoff_date = features_a.index[619]
    for name in CANDIDATE_NAMES:
        pd.testing.assert_series_equal(
            signals_a[name].loc[:cutoff_date],
            signals_b[name].loc[:cutoff_date],
            check_names=True,
        )


def test_candidate_set_is_frozen_and_binary() -> None:
    features = build_features(_synthetic_ohlcv(500))
    positions = build_candidate_positions(features)
    assert tuple(positions) == CANDIDATE_NAMES
    for position in positions.values():
        assert set(position.unique()).issubset({0.0, 1.0})


def test_research_returns_governed_decision() -> None:
    daily = _synthetic_ohlcv(3900, start="2010-01-04")
    cutoff = pd.Timestamp(daily["date"].iloc[-1])
    contract = {
        "experiment_id": "test_byd_v1_0",
        "costs": {
            "primary_bps_per_turnover_unit": 20,
            "stress_bps_per_turnover_unit": [10, 20, 40],
        },
        "windows": {
            "development_start": "2012-01-01",
            "development_end": "2020-12-31",
            "validation_start": "2021-01-01",
            "validation_end": "2022-12-31",
            "quarantine_start": "2023-01-01",
            "quarantine_end": cutoff.strftime("%Y-%m-%d"),
        },
    }
    summary = evaluate_research(daily, contract)
    assert summary["decision"] in {
        "byd_v1_0_supported",
        "byd_v1_0_not_supported",
    }
    assert len(summary["candidate_rows"]) == 5
    assert summary["research_only"] is True
    assert summary["trade_ready"] is False
