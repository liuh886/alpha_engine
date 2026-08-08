from __future__ import annotations

import math

import pandas as pd

from src.dashboard.market_evidence import (
    _bars,
    _chart_studies,
    _factor_stats,
    _trade_events,
)
from src.factors.library import load_factor_library


def _price_frame(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = pd.Series([100.0 + index * 0.4 + math.sin(index / 4) for index in range(rows)])
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [1_000_000 + index * 100 for index in range(rows)],
        }
    )


def test_chart_studies_share_the_same_ohlcv_clock() -> None:
    frame = _price_frame()
    studies = _chart_studies(frame)
    assert studies["boll20"]
    assert studies["macd_12_26_9"]
    assert studies["rsi14"]
    assert studies["boll20"][-1]["time"] == frame.iloc[-1]["date"].date().isoformat()
    assert 0.0 <= studies["rsi14"][-1]["value"] <= 100.0


def test_bars_retain_real_ohlcv_and_reject_invalid_rows() -> None:
    frame = _price_frame(3)
    frame.loc[1, "high"] = frame.loc[1, "low"] - 1.0
    rows = _bars(frame)
    assert len(rows) == 2
    assert rows[0]["open"] != rows[0]["close"]
    assert rows[0]["volume"] > 0


def test_trade_events_keep_model_identity_for_cross_model_overlay() -> None:
    packages = [
        {
            "model_id": "us_x1_1",
            "display_name": "US x1.1",
            "backtest_id": "run-a",
            "positions": [{"instrument": "AAPL", "name": "Apple", "date": "2026-01-02", "weight": 0.1}],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "AAPL",
                    "action": "BUY",
                    "previous_weight": 0.0,
                    "target_weight": 0.1,
                    "weight_delta": 0.1,
                    "reason": "rank_rebalance",
                }
            ],
        },
        {
            "model_id": "us_x1_2",
            "display_name": "US x1.2",
            "backtest_id": "run-b",
            "positions": [],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "AAPL",
                    "action": "DECREASE",
                    "previous_weight": 0.1,
                    "target_weight": 0.05,
                    "weight_delta": -0.05,
                }
            ],
        },
    ]
    events, labels = _trade_events(packages)
    assert labels["AAPL"] == "Apple"
    assert [row["model_id"] for row in events["AAPL"]] == ["us_x1_1", "us_x1_2"]
    assert all(row["research_only"] is True for row in events["AAPL"])
    assert all(row["trade_ready"] is False for row in events["AAPL"])


def test_factor_statistics_are_distribution_evidence_not_importance() -> None:
    library = load_factor_library("configs/factor_libraries/ohlcv.yaml")
    factor_id = "ohlcv.momentum.ret_10d"
    values = pd.DataFrame({factor_id: [float(value) / 100 for value in range(-50, 51)]})
    rows = _factor_stats(
        values,
        library,
        [factor_id],
        market="us",
        pool_id="test_pool",
        start="2026-01-01",
        cutoff="2026-06-30",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ready"
    assert row["sample_count"] == 101
    assert row["median"] == 0.0
    assert len(row["histogram"]) == 24
    assert "importance" not in row
