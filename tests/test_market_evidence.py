from __future__ import annotations

import math

import pandas as pd

from src.dashboard.market_evidence import (
    _bars,
    _chart_studies,
    _factor_stats,
    _provider_symbol_for_formal_instrument,
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


def _monotonic_frame(direction: int, rows: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = pd.Series([100.0 + direction * index for index in range(rows)])
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [1_000_000] * rows,
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


def test_rsi_handles_zero_loss_zero_gain_and_flat_boundaries() -> None:
    rising = _chart_studies(_monotonic_frame(1))["rsi14"]
    falling = _chart_studies(_monotonic_frame(-1))["rsi14"]
    flat = _chart_studies(_monotonic_frame(0))["rsi14"]
    assert rising[-1]["value"] == 100.0
    assert falling[-1]["value"] == 0.0
    assert flat[-1]["value"] == 50.0


def test_bars_retain_real_ohlcv_and_reject_invalid_rows() -> None:
    frame = _price_frame(3)
    frame.loc[1, "high"] = frame.loc[1, "low"] - 1.0
    rows = _bars(frame)
    assert len(rows) == 2
    assert rows[0]["open"] != rows[0]["close"]
    assert rows[0]["volume"] > 0


def test_formal_instrument_identity_maps_to_provider_without_browser_aliases() -> None:
    assert _provider_symbol_for_formal_instrument("cn", "BYD") == "002594"
    assert _provider_symbol_for_formal_instrument("cn", "515180.SH") == "515180"
    assert _provider_symbol_for_formal_instrument("cn", "600519.SH") == "600519"
    assert _provider_symbol_for_formal_instrument("us", "QQQI") == "QQQI"
    assert _provider_symbol_for_formal_instrument("us", "CASH") is None


def test_trade_events_keep_model_and_canonical_instrument_identity() -> None:
    packages = [
        {
            "model_id": "byd_v1_2",
            "display_name": "BYD v1.2",
            "backtest_id": "run-a",
            "positions": [{"instrument": "BYD", "name": "比亚迪", "date": "2026-01-02", "weight": 0.75}],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "BYD",
                    "action": "BUY",
                    "previous_weight": 0.0,
                    "target_weight": 0.75,
                    "weight_delta": 0.75,
                    "reason": "allocation_change",
                },
                {
                    "date": "2026-01-02",
                    "instrument": "515180.SH",
                    "action": "BUY",
                    "previous_weight": 0.0,
                    "target_weight": 0.25,
                    "weight_delta": 0.25,
                },
                {
                    "date": "2026-01-02",
                    "instrument": "CASH",
                    "action": "SELL",
                    "previous_weight": 1.0,
                    "target_weight": 0.0,
                    "weight_delta": -1.0,
                },
            ],
        },
        {
            "model_id": "cn_x1_1",
            "display_name": "CN x1.1",
            "backtest_id": "run-b",
            "positions": [],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "002594",
                    "action": "DECREASE",
                    "previous_weight": 0.1,
                    "target_weight": 0.05,
                    "weight_delta": -0.05,
                }
            ],
        },
    ]
    events, labels = _trade_events(packages, "cn")
    assert labels["002594"] == "比亚迪"
    assert [row["model_id"] for row in events["002594"]] == ["byd_v1_2", "cn_x1_1"]
    assert events["002594"][0]["source_instrument"] == "BYD"
    assert events["002594"][0]["instrument_id"] == "cn:002594"
    assert events["515180"][0]["source_instrument"] == "515180.SH"
    assert "CASH" not in events
    assert all(row["research_only"] is True for row in events["002594"])
    assert all(row["trade_ready"] is False for row in events["002594"])


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
