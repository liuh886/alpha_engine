from __future__ import annotations

import pandas as pd

from src.artifacts.qqq_v4_3_formal import JOINT_STRATEGY, MODEL_ID, build_formal_package
from src.research.etf_rotation_experiment import StrategyResult, _return_metrics


def _bars(index: pd.DatetimeIndex, start: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": index,
            "open": [start + i for i in range(len(index))],
            "close": [start + i + 0.2 for i in range(len(index))],
        }
    )


def test_formal_package_retains_dynamic_sgov_and_panic_weights() -> None:
    index = pd.date_range("2026-07-27", periods=5, freq="B")
    daily = pd.DataFrame(
        {
            "net_return": [0.0, -0.01, 0.02, 0.015, -0.005],
            "gross_return": [0.001, -0.009, 0.021, 0.016, -0.004],
            "transaction_cost": [0.001] * 5,
            "turnover_units": [1.0, 1.0, 1.0, 0.0, 0.0],
            "QQQI_next_open_return": [0.0, -0.01, 0.01, 0.01, -0.01],
            "QQQ_next_open_return": [0.0, -0.02, 0.02, 0.01, -0.01],
            "TQQQ_next_open_return": [0.0, -0.05, 0.06, 0.03, -0.03],
            "SGOV_next_open_return": [0.0, 0.0002, 0.0002, 0.0002, 0.0002],
            "position_state": [0, 0, 0, 1, 2],
            "position_label": ["defensive", "defensive", "defensive", "attack", "partial_leverage"],
            "decision_state": [0, 0, 1, 2, 2],
            "decision_reason": ["hold"] * 5,
            "executed_reason": ["initial_entry", "hold", "hold", "repair", "leverage"],
            "panic_repair_active_at_open": [False, False, True, False, False],
            "ma200_ma20_vix_defense_active": [False, True, False, False, False],
            "weight_QQQI": [1.0, 0.5, 0.75, 0.5, 0.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.5, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.25, 0.0, 0.75],
            "weight_SGOV": [0.0, 0.5, 0.0, 0.0, 0.0],
            "vix_close": [18.0, 25.0, 20.0, 17.0, 16.0],
            "vix_regime": ["normal", "stress", "normal", "normal", "calm"],
            "vxn_close": [20.0, 28.0, 23.0, 20.0, 19.0],
            "vxn_regime": ["normal", "stress", "normal", "normal", "calm"],
        },
        index=index,
    )
    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    metrics.update(
        {
            "strategy": JOINT_STRATEGY,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
        }
    )
    result = StrategyResult(JOINT_STRATEGY, daily, pd.DataFrame(), metrics)
    bars = {
        "QQQI": _bars(index, 35.0),
        "QQQ": _bars(index, 550.0),
        "TQQQ": _bars(index, 80.0),
        "SGOV": _bars(index, 100.0),
    }
    package = build_formal_package(
        result,
        bars,
        generated_at="2026-08-08T00:00:00Z",
        evidence_cutoff="2026-07-31",
        backtest_id="test-v4-3",
        evidence={"test": True},
    )

    assert package["model_id"] == MODEL_ID
    assert package["publication_status"] == "accepted_formal_baseline"
    assert package["portfolio_contract"]["symbols"] == ["QQQI", "QQQ", "TQQQ", "SGOV"]
    assert any(row["instrument"] == "SGOV" and row["weight"] == 0.5 for row in package["positions"])
    assert any(row["panic_repair_active"] for row in package["report"])
    assert package["research_only"] is True
    assert package["trade_ready"] is False
