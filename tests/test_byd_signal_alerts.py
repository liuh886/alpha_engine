"""Contract tests for the formal BYD v1.2 signal layer."""
from __future__ import annotations

import json

import pytest

from src.research.byd_signal_alerts import (
    _momentum_scale,
    _orders,
    _target_weights,
    build_byd_signal_alert,
)


def _shadow(
    *,
    base_target: float = 1.0,
    signal_date: str = "2026-08-06",
    eligible: bool = True,
) -> dict:
    return {
        "base_target_position": base_target,
        "signal_date": signal_date,
        "open_research_eligible": eligible,
        "prospective_eligible": eligible,
        "data_version": "shadow-v1",
        "chain_linked_adjusted_ohlcv": {"close": 95.0, "open": 94.0},
    }


def _paired(
    *,
    signal_date: str = "2026-08-06",
    eligible: bool = True,
) -> dict:
    return {
        "signal_date": signal_date,
        "common_open_eligible": eligible,
        "prospective_eligible": eligible,
        "data_version": "paired-v1",
    }


def _expansion(
    *,
    active: bool = False,
    mom_20: float = 0.0,
    signal_date: str = "2026-08-06",
    eligible: bool = True,
) -> dict:
    return {
        "signal_date": signal_date,
        "common_open_eligible": eligible,
        "prospective_eligible": eligible,
        "trend_expansion_active": active,
        "data_version": "expansion-v1",
        "factors": {
            "market_state": "bull",
            "vol_state": "low",
            "drawdown_252": -0.08,
            "mom_20": mom_20,
            "mom_60": 0.10,
        },
    }


def test_momentum_scale_matches_frozen_contract() -> None:
    assert _momentum_scale(-0.10) == 0.0
    assert _momentum_scale(0.0) == 0.0
    assert _momentum_scale(0.15) == 1.0
    assert _momentum_scale(0.30) == 1.0
    assert _momentum_scale(0.075) == pytest.approx(0.5**4)


def test_target_weights_are_continuous_and_bounded() -> None:
    target, scale, increment = _target_weights(
        base_target=1.0,
        expansion_active=True,
        momentum_20=0.075,
    )
    assert scale == pytest.approx(0.0625)
    assert increment == pytest.approx(0.0078125)
    assert target == pytest.approx(
        {"BYD": 1.0078125, "515180": 0.0, "CASH": -0.0078125}
    )
    assert sum(target.values()) == pytest.approx(1.0)


def test_defense_target_uses_515180_sleeve() -> None:
    target, scale, increment = _target_weights(
        base_target=0.75,
        expansion_active=False,
        momentum_20=0.20,
    )
    assert scale == 1.0
    assert increment == 0.0
    assert target == {"BYD": 0.75, "515180": 0.25, "CASH": 0.0}


def test_orders_include_financing_leg() -> None:
    current = {"BYD": 1.0, "515180": 0.0, "CASH": 0.0}
    target = {"BYD": 1.05, "515180": 0.0, "CASH": -0.05}
    orders = _orders(current, target)
    assert len(orders) == 2
    assert next(row for row in orders if row["asset"] == "BYD")["side"] == "buy"
    assert next(row for row in orders if row["asset"] == "CASH")["side"] == "sell"


def test_first_formal_signal_alerts_current_target() -> None:
    alert = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.15),
    )
    assert alert["should_alert"] is True
    assert alert["transition_type"] == "initialize"
    assert alert["target_mode"] == "convex_expansion"
    assert alert["target_weights"] == {
        "BYD": 1.125,
        "515180": 0.0,
        "CASH": -0.125,
    }


def test_unchanged_target_does_not_alert() -> None:
    first = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.075),
    )
    second = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.075),
        previous_alert=first,
    )
    assert second["should_alert"] is False
    assert second["transition_type"] == "no_change"


def test_continuous_weight_change_alerts() -> None:
    previous = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.075),
    )
    current = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.12),
        previous_alert=previous,
    )
    assert current["should_alert"] is True
    assert current["transition_type"] == "rebalance"
    assert current["target_weights"]["BYD"] > previous["target_weights"]["BYD"]


def test_ineligible_source_blocks_delivery() -> None:
    alert = build_byd_signal_alert(
        _shadow(eligible=False),
        _paired(),
        _expansion(active=True, mom_20=0.15),
    )
    assert alert["should_alert"] is False
    assert alert["data_freshness_ok"] is False
    assert alert["open_research_eligible"] is False


def test_source_date_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="dates do not agree"):
        build_byd_signal_alert(
            _shadow(signal_date="2026-08-05"),
            _paired(signal_date="2026-08-06"),
            _expansion(signal_date="2026-08-06"),
        )


def test_fingerprint_is_deterministic() -> None:
    first = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.10),
    )
    second = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.10),
    )
    assert first["fingerprint"] == second["fingerprint"]


def test_markdown_and_json_are_frontend_readable() -> None:
    alert = build_byd_signal_alert(
        _shadow(),
        _paired(),
        _expansion(active=True, mom_20=0.10),
    )
    assert f"signal-fingerprint:{alert['fingerprint']}" in alert["markdown"]
    assert len(alert["telegram_text"]) <= 4096
    decoded = json.loads(json.dumps(alert, ensure_ascii=False, sort_keys=True))
    assert decoded["model_id"] == "byd_v1_2_convex_momentum_budget_v1"
    assert decoded["target_weights"] == alert["target_weights"]
