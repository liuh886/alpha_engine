from __future__ import annotations

from src.research.strategy_signal_alerts import build_signal_alert


def _contract() -> dict:
    return {
        "experiment_id": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "portfolio": {
            "state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
            "state_1_bridge": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
            "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
            "transaction_cost_bps_per_turnover_unit": 10.0,
        },
    }


def _policy() -> dict:
    return {
        "alert_decision_support": {
            "transitions": {
                "open_risk_bridge": {
                    "confidence": "中等",
                    "historical_evidence": "失败恢复周期中多数占优。",
                    "next_confirmation": "等待中期修复与波动率正常化。",
                    "invalidation": "长期防线失守时返回防守。",
                    "principal_risk": "可能反复。",
                },
                "add_tqqq_leverage": {
                    "confidence": "较高",
                    "historical_evidence": "样本内最强转换。",
                    "next_confirmation": "继续监控。",
                    "invalidation": "波动率压力或 MA20 退出。",
                    "principal_risk": "TQQQ 尾部风险。",
                },
            }
        }
    }


def _summary(
    executed_state: int,
    decision_state: int,
    *,
    latest_data_date: str = "2026-08-03",
) -> dict:
    weights = {
        0: {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
        1: {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
        2: {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
    }
    return {
        "latest_data_date": latest_data_date,
        "data_identity": {
            "mode": "governed_etf_bundle",
            "bundle_id": "test-bundle",
        },
        "bridge_latest_snapshot": {
            "latest_executed_position": {
                "position_state": executed_state,
                "weights": weights[executed_state],
                "state_entry_date": "2026-07-30",
                "state_age_sessions": 3,
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
                "price_context": {
                    "qqq_close": 500.0,
                    "qqq_vs_ma20": 0.01,
                    "qqq_vs_ma50": 0.02,
                    "qqq_vs_ma200": 0.10,
                    "shock_drawdown_now": -0.05,
                    "shock_memory": True,
                    "early_repair": True,
                    "medium_repair": False,
                    "secondary_confirmation": False,
                },
                "volatility_context": {
                    "vix_close": 18.0,
                    "vix_q_normal": 19.0,
                    "vix_q_stress": 27.0,
                    "vix_retreat_from_peak": -0.20,
                    "vxn_close": 22.0,
                    "vxn_q_normal": 23.0,
                    "vxn_q_stress": 31.0,
                    "vxn_retreat_from_peak": -0.18,
                },
            },
        },
    }


def test_defense_to_bridge_emits_half_rebalance() -> None:
    alert = build_signal_alert(_summary(0, 1), _contract(), _policy())
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
    assert alert["turnover_units"] == 1.0
    assert alert["estimated_transaction_cost"] == 0.001
    assert "下一确认" in alert["telegram_text"]
    assert "模型成本约 0.10%" in alert["telegram_text"]


def test_bridge_to_leverage_emits_qqqi_exit_and_tqqq_buy() -> None:
    alert = build_signal_alert(_summary(1, 2), _contract(), _policy())
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
    assert "TQQQ 尾部风险" in alert["telegram_text"]


def test_unchanged_state_does_not_alert() -> None:
    alert = build_signal_alert(_summary(1, 1), _contract(), _policy())
    assert alert["should_alert"] is False
    assert alert["orders"] == []


def test_stale_signal_is_blocked() -> None:
    alert = build_signal_alert(
        _summary(0, 1, latest_data_date="2026-08-04"),
        _contract(),
        _policy(),
    )
    assert alert["data_freshness_ok"] is False
    assert alert["should_alert"] is False
    assert "禁止执行" in alert["telegram_text"]


def test_fingerprint_is_deterministic_and_telegram_is_bounded() -> None:
    left = build_signal_alert(_summary(2, 0), _contract(), _policy())
    right = build_signal_alert(_summary(2, 0), _contract(), _policy())
    assert left["fingerprint"] == right["fingerprint"]
    assert "signal-fingerprint" in left["markdown"]
    assert len(left["telegram_text"]) <= 4096
