from __future__ import annotations

import pytest

from src.factors.strategy_snapshot import (
    StrategyFactorSnapshotError,
    build_strategy_factor_snapshot,
    validate_strategy_factor_snapshot,
)


def _qqq_signal(*, fresh: bool = True) -> dict[str, object]:
    return {
        "signal_date": "2026-08-07",
        "latest_data_date": "2026-08-07",
        "data_freshness_ok": fresh,
        "price_context": {
            "qqq_vs_ma20": 0.02,
            "qqq_vs_ma200": 0.11,
            "stress_price_failure": False,
            "long_break": False,
        },
        "volatility_context": {
            "vix_close": 16.0,
            "vix_q_normal": 18.0,
            "vix_q_stress": 22.0,
            "vix_regime": "calm",
            "vix_stress": False,
            "vix_easing": True,
            "vix_normalized": True,
            "vxn_close": 24.0,
            "vxn_q_normal": 25.0,
            "vxn_q_stress": 29.0,
            "vxn_regime": "calm",
            "vxn_stress": False,
        },
    }


def _byd_signal() -> dict[str, object]:
    return {
        "signal_date": "2026-08-07",
        "latest_data_date": "2026-08-07",
        "data_freshness_ok": True,
        "target_mode": "defense",
        "expansion_active": False,
        "factor_context": {
            "market_state": "bear",
            "vol_state": "high",
            "mom_20": 0.0042,
            "mom_60": -0.0846,
            "drawdown_252": -0.2076,
            "momentum_scale": 1.0,
            "financed_increment": 0.0,
        },
    }


def test_qqq_snapshot_binds_canonical_factor_ids_and_cutoff() -> None:
    snapshot = build_strategy_factor_snapshot(
        model_family_id="qqq_rotation", signal=_qqq_signal()
    )
    validate_strategy_factor_snapshot(snapshot)
    assert snapshot["freshness"] == "current"
    assert snapshot["observation_cutoff"] == "2026-08-07"
    assert snapshot["factor_count"] == 4
    assert {row["factor_id"] for row in snapshot["factors"]} == {
        "strategy.qqq.vix_close",
        "strategy.qqq.vxn_close",
        "strategy.qqq.qqq_vs_ma20",
        "strategy.qqq.qqq_vs_ma200",
    }
    assert all(len(row["implementation_hash"]) == 64 for row in snapshot["factors"])


def test_stale_data_produces_stale_factor_snapshot() -> None:
    snapshot = build_strategy_factor_snapshot(
        model_family_id="qqq_rotation", signal=_qqq_signal(fresh=False)
    )
    assert snapshot["freshness"] == "stale"


def test_missing_required_qqq_factor_fails_closed() -> None:
    signal = _qqq_signal()
    del signal["price_context"]["qqq_vs_ma200"]  # type: ignore[index]
    with pytest.raises(StrategyFactorSnapshotError, match="has no observation"):
        build_strategy_factor_snapshot(model_family_id="qqq_rotation", signal=signal)


def test_byd_snapshot_exposes_rule_state_without_pseudo_shap() -> None:
    snapshot = build_strategy_factor_snapshot(
        model_family_id="byd_allocation", signal=_byd_signal()
    )
    assert snapshot["factor_count"] == 8
    by_id = {row["factor_id"]: row for row in snapshot["factors"]}
    assert by_id["strategy.byd.market_state"]["value"] == "bear"
    assert by_id["strategy.byd.expansion_active"]["value"] is False
    assert by_id["strategy.byd.financed_increment"]["effect"] == "neutral"


def test_snapshot_rejects_mismatched_signal_and_observation_cutoff() -> None:
    snapshot = build_strategy_factor_snapshot(
        model_family_id="qqq_rotation", signal=_qqq_signal()
    )
    snapshot["observation_cutoff"] = "2026-08-06"
    with pytest.raises(StrategyFactorSnapshotError, match="must match"):
        validate_strategy_factor_snapshot(snapshot)
