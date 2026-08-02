from __future__ import annotations

from src.research.strategy_signal_alerts import build_signal_alert


def _contract() -> dict:
    return {
        "experiment_id": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "portfolio": {
            "state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
            "state_1_bridge": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
            "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
        },
    }


def _summary(executed_state: int, decision_state: int) -> dict:
    weights = {
        0: {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
        1: {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
        2: {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
    }
    return {
        "bridge_latest_snapshot": {
            "latest_executed_position": {
                "position_state": executed_state,
                "weights": weights[executed_state],
            },
            "latest_close_signal": {
                "signal_date": "2026-08-03",
                "decision_state": decision_state,
                "decision_reason": "test_reason",
                "vix_close": 18.0,
                "vxn_close": 22.0,
                "vix_stress": False,
                "vix_easing": True,
                "vix_normalized": True,
                "vxn_stress": False,
            },
        }
    }


def test_defense_to_bridge_emits_half_rebalance() -> None:
    alert = build_signal_alert(_summary(0, 1), _contract())
    assert alert["should_alert"] is True
    assert alert["transition_type"] == "open_risk_bridge"
    assert alert["orders"] == [
        {
            "asset": "QQQI",
            "side": "sell",
            "weight_change": 0.5,
            "from_weight": 1.0,
            "to_weight": 0.5,
        },
        {
            "asset": "QQQ",
            "side": "buy",
            "weight_change": 0.5,
            "from_weight": 0.0,
            "to_weight": 0.5,
        },
    ]


def test_bridge_to_leverage_emits_qqqi_exit_and_tqqq_buy() -> None:
    alert = build_signal_alert(_summary(1, 2), _contract())
    assert alert["should_alert"] is True
    assert alert["transition_type"] == "add_tqqq_leverage"
    assert {row["asset"] for row in alert["orders"]} == {"QQQI", "QQQ", "TQQQ"}
    assert next(row for row in alert["orders"] if row["asset"] == "TQQQ") == {
        "asset": "TQQQ",
        "side": "buy",
        "weight_change": 0.75,
        "from_weight": 0.0,
        "to_weight": 0.75,
    }


def test_unchanged_state_does_not_alert() -> None:
    alert = build_signal_alert(_summary(1, 1), _contract())
    assert alert["should_alert"] is False
    assert alert["orders"] == []


def test_fingerprint_is_deterministic() -> None:
    left = build_signal_alert(_summary(2, 0), _contract())
    right = build_signal_alert(_summary(2, 0), _contract())
    assert left["fingerprint"] == right["fingerprint"]
    assert "signal-fingerprint" in left["markdown"]
