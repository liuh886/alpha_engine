from __future__ import annotations

import pandas as pd

from src.research.qqq_v4_3_monitor import latest_next_open_target
from src.research.qqq_v4_3_signal_alerts import build_v4_3_signal_alert


def test_latest_target_enters_sgov_defense_inside_same_formal_state() -> None:
    index = pd.date_range("2026-06-01", periods=20, freq="B")
    prepared = pd.DataFrame(
        {
            "qqq_close": [120.0 - i for i in range(20)],
            "ma_short": [110.0] * 20,
            "ma_medium": [115.0] * 20,
            "ma_long": [125.0 - i * 0.1 for i in range(20)],
            "early_repair": [False] * 20,
            "stress_price_failure": [True] * 20,
            "vix_easing": [False] * 20,
            "vix_normalized": [False] * 20,
            "vix_close": [28.0] * 20,
            "vxn_close": [32.0] * 20,
            "vix_regime": ["stress"] * 20,
            "vxn_regime": ["stress"] * 20,
            "shock_memory": [True] * 20,
        },
        index=index,
    )
    decisions = pd.DataFrame(
        {"decision_state": [0] * 20, "decision_reason": ["hold"] * 20},
        index=index,
    )
    fear_greed = pd.DataFrame(
        {"fear_greed_score": [50.0] * 20},
        index=index,
    )
    qqq_close = prepared["qqq_close"]

    target = latest_next_open_target(prepared, decisions, fear_greed, qqq_close)

    assert target["formal_state"] == 0
    assert target["strong_defense"] is True
    assert target["overlay"] == "ma200_slow_bear_defense"
    assert target["target_weights"] == {
        "QQQI": 0.5,
        "QQQ": 0.0,
        "TQQQ": 0.0,
        "SGOV": 0.5,
    }


def test_signal_alert_fires_on_same_state_weight_change() -> None:
    context = {
        "qqq_close": 710.0,
        "ma20": 705.0,
        "ma50": 700.0,
        "ma200": 640.0,
        "stress_price_failure": False,
        "vix_close": 16.2,
        "vxn_close": 24.1,
        "vix_easing": True,
        "vix_normalized": True,
        "vix_regime": "calm",
        "vxn_regime": "calm",
    }
    current = {
        "signal_date": "2026-08-06",
        "formal_state": 0,
        "target_weights": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
        "overlay": "formal_state_allocation",
        "panic_repair_active": False,
        "strong_defense": False,
        "ma200_falling": False,
        "fast_price_vol_repair": False,
        "rsi_14": 45.0,
        "fear_greed_score": 40.0,
        "context": context,
    }
    target = {
        **current,
        "target_weights": {"QQQI": 0.5, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.5},
        "overlay": "ma200_slow_bear_defense",
        "strong_defense": True,
        "ma200_falling": True,
    }
    summary = {
        "latest_data_date": "2026-08-06",
        "current_open_target": current,
        "next_open_target": target,
        "data_identity": {"mode": "governed"},
    }

    alert = build_v4_3_signal_alert(summary)

    assert alert["should_alert"] is True
    assert alert["current_formal_state"] == alert["target_formal_state"] == 0
    assert any(row["asset"] == "SGOV" and row["side"] == "buy" for row in alert["orders"])
