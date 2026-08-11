"""Contract tests for the formal BYD v1.3 signal layer."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.research.byd_signal_alerts import MODEL_ID, _orders, build_byd_signal_alert


def _observation(
    *,
    byd_weight: float = 0.75,
    etf_weight: float = 0.25,
    cash_weight: float = 0.0,
    vol_state: str = "high",
    event_edge: bool = False,
    entry_confirmed: bool = False,
    lifecycle_active: bool = False,
    expansion_active: bool = False,
    financed_increment: float = 0.0,
    common_open: bool = True,
    signal_date: str = "2026-08-10",
) -> dict:
    return {
        "schema_version": "byd_v1_3_low_vol_prospective_v1",
        "candidate_model_id": MODEL_ID,
        "signal_date": signal_date,
        "data_version": f"v1-3-{signal_date}",
        "common_open_eligible": common_open,
        "prospective_eligible": False,
        "prelaunch_seed": signal_date == "2026-08-10",
        "source": {"recovery_event_observation_sha256": "a" * 64},
        "prices": {"byd_open": 90.0, "etf_open": 1.41},
        "champion": {
            "model_id": "byd_v1_2_convex_momentum_budget_v1",
            "base_byd_weight": 0.75,
            "trend_expansion_active": expansion_active,
            "momentum_scale": 0.25 if expansion_active else 0.0,
            "financed_increment": financed_increment,
        },
        "factors": {
            "market_state": "bear",
            "vol_state": vol_state,
            "drawdown_252": -0.20,
            "mom_20": 0.05,
            "mom_60": -0.03,
        },
        "detector": {
            "active": event_edge,
            "event_edge": event_edge,
            "drawdown252_x_rebound60": 0.03,
            "threshold": 0.026937,
        },
        "entry_confirmation": {
            "required_vol_state": "low",
            "observed_vol_state": vol_state,
            "passed_on_edge": entry_confirmed,
            "catch_up_allowed": False,
        },
        "lifecycle": {
            "overlay_decision_active": lifecycle_active,
            "started": lifecycle_active,
            "id": 1 if lifecycle_active else 0,
            "remaining_eligible_sessions": 20 if lifecycle_active else 0,
        },
        "targets": {
            "byd_v1_2_convex_momentum_budget_v1": {
                "byd_weight": 0.75,
                "etf_weight": 0.25,
                "cash_weight": 0.0,
            },
            MODEL_ID: {
                "byd_weight": byd_weight,
                "etf_weight": etf_weight,
                "cash_weight": cash_weight,
            },
        },
    }


def test_signal_consumes_final_governed_target_without_recomputing() -> None:
    alert = build_byd_signal_alert(
        _observation(
            byd_weight=1.0,
            etf_weight=0.0,
            vol_state="low",
            event_edge=True,
            entry_confirmed=True,
            lifecycle_active=True,
        )
    )
    assert alert["model_id"] == MODEL_ID
    assert alert["target_mode"] == "low_vol_recovery"
    assert alert["target_weights"] == {"BYD": 1.0, "515180": 0.0, "CASH": 0.0}
    assert alert["recovery_context"]["entry_confirmed"] is True
    assert alert["should_alert"] is True


def test_prelaunch_seed_can_initialize_formal_signal_without_becoming_forward_evidence() -> None:
    alert = build_byd_signal_alert(_observation())
    assert alert["transition_type"] == "initialize"
    assert alert["data_freshness_ok"] is True
    assert alert["source_identity"]["prospective_evidence_eligible"] is False
    assert alert["source_identity"]["prelaunch_seed"] is True
    assert alert["should_alert"] is True


def test_immutable_legacy_prelaunch_seed_proves_identity_from_frozen_contract() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation["kind"] = "v1_3_low_vol_recovery_observation"
    observation["launch_after"] = "2026-08-10"

    alert = build_byd_signal_alert(observation)

    assert alert["model_id"] == MODEL_ID
    assert alert["data_freshness_ok"] is True


def test_missing_identity_outside_legacy_seed_fails_closed() -> None:
    observation = _observation(signal_date="2026-08-11")
    observation.pop("candidate_model_id")
    observation["kind"] = "v1_3_low_vol_recovery_observation"
    observation["launch_after"] = "2026-08-10"

    with pytest.raises(ValueError, match="wrong model identity"):
        build_byd_signal_alert(observation)


def test_unchanged_target_does_not_alert() -> None:
    first = build_byd_signal_alert(_observation())
    second = build_byd_signal_alert(_observation(), previous_alert=first)
    assert second["should_alert"] is False
    assert second["transition_type"] == "no_change"


def test_changed_final_target_produces_orders() -> None:
    previous = build_byd_signal_alert(_observation())
    current = build_byd_signal_alert(
        _observation(
            byd_weight=1.0,
            etf_weight=0.0,
            vol_state="low",
            event_edge=True,
            entry_confirmed=True,
            lifecycle_active=True,
            signal_date="2026-08-11",
        ),
        previous_alert=previous,
    )
    assert current["transition_type"] == "rebalance"
    assert current["should_alert"] is True
    assert next(row for row in current["orders"] if row["asset"] == "BYD") == {
        "asset": "BYD",
        "side": "buy",
        "weight_change": pytest.approx(0.25),
        "from_weight": pytest.approx(0.75),
        "to_weight": pytest.approx(1.0),
    }


def test_financed_v1_2_core_target_remains_visible_when_recovery_is_inactive() -> None:
    alert = build_byd_signal_alert(
        _observation(
            byd_weight=1.05,
            etf_weight=0.0,
            cash_weight=-0.05,
            expansion_active=True,
            financed_increment=0.05,
        )
    )
    assert alert["target_mode"] == "convex_expansion"
    assert alert["target_weights"]["CASH"] == pytest.approx(-0.05)


def test_common_open_quarantine_does_not_rewrite_close_target() -> None:
    alert = build_byd_signal_alert(_observation(common_open=False))
    assert alert["data_freshness_ok"] is True
    assert alert["open_research_eligible"] is False
    assert alert["target_weights"] == {"BYD": 0.75, "515180": 0.25, "CASH": 0.0}


def test_wrong_candidate_identity_fails_closed() -> None:
    observation = _observation()
    observation["candidate_model_id"] = "wrong"
    with pytest.raises(ValueError, match="wrong model identity"):
        build_byd_signal_alert(observation)


def test_invalid_governed_target_fails_closed() -> None:
    observation = _observation()
    observation["targets"][MODEL_ID]["byd_weight"] = 1.2
    with pytest.raises(ValueError, match="sum to one"):
        build_byd_signal_alert(observation)


def test_orders_include_financing_leg() -> None:
    orders = _orders(
        {"BYD": 1.0, "515180": 0.0, "CASH": 0.0},
        {"BYD": 1.05, "515180": 0.0, "CASH": -0.05},
    )
    assert len(orders) == 2
    assert next(row for row in orders if row["asset"] == "CASH")["side"] == "sell"


def test_fingerprint_is_deterministic_and_target_sensitive() -> None:
    first = build_byd_signal_alert(_observation())
    second = build_byd_signal_alert(deepcopy(_observation()))
    changed = build_byd_signal_alert(
        _observation(byd_weight=1.0, etf_weight=0.0, signal_date="2026-08-11")
    )
    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"] != changed["fingerprint"]


def test_markdown_and_json_are_frontend_readable() -> None:
    alert = build_byd_signal_alert(_observation())
    assert "BYD v1.3" in alert["title"]
    assert f"signal-fingerprint:{alert['fingerprint']}" in alert["markdown"]
    assert len(alert["telegram_text"]) <= 4096
    decoded = json.loads(json.dumps(alert, ensure_ascii=False, sort_keys=True))
    assert decoded["model_id"] == MODEL_ID
    assert decoded["target_weights"] == alert["target_weights"]
