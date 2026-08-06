"""Contract tests for BYD signal alert logic."""

from __future__ import annotations

import json

import pytest

from src.research.byd_signal_alerts import (
    STATE_LABELS,
    TRANSITION_LABELS,
    _decide_state,
    _target_weights,
    _transition_type,
    _orders,
    build_byd_signal_alert,
)


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

def _mock_shadow_obs(*, base_target=1.0, signal_date="2026-08-06", eligible=True):
    return {
        "base_target_position": base_target,
        "signal_date": signal_date,
        "open_research_eligible": eligible,
        "prospective_eligible": True,
        "data_version": "test-v1",
        "provider_payload_sha256": "abc123",
        "chain_linked_adjusted_ohlcv": {"close": 95.0, "open": 94.0},
        "primary_raw_ohlcv": {"close": 95.0, "open": 94.0},
        "factors": {
            "market_state": "bull",
            "vol_state": "low",
            "drawdown_252": -0.08,
            "momentum_accel_20_60": 0.05,
            "open_return_autocorr_20": 0.03,
            "distance_from_low_20": 0.10,
        },
    }


def _mock_expansion_obs(*, active=False):
    return {"trend_expansion_active": active}


def _mock_paired_obs():
    return {"factors": {}}


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_defense_state(self):
        assert _decide_state(0.75, False) == 0
        assert _decide_state(0.75, True) == 0  # expansion not active at 0.75

    def test_offense_state(self):
        assert _decide_state(1.0, False) == 1

    def test_expansion_state(self):
        assert _decide_state(1.0, True) == 2

    def test_expansion_only_at_full_base(self):
        assert _decide_state(0.99, True) == 2
        assert _decide_state(0.75, True) == 0  # not at full base


class TestTargetWeights:
    def test_defense_weights(self):
        w = _target_weights(0)
        assert w == {"BYD": 0.75, "515180": 0.25, "CASH": 0.0}

    def test_offense_weights(self):
        w = _target_weights(1)
        assert w == {"BYD": 1.00, "515180": 0.0, "CASH": 0.0}

    def test_expansion_weights(self):
        w = _target_weights(2)
        assert w == {"BYD": 1.10, "515180": 0.0, "CASH": -0.10}
        assert sum(w.values()) == pytest.approx(1.0)


class TestTransitions:
    def test_enter_offense(self):
        assert _transition_type(0, 1) == "enter_offense"

    def test_enter_defense(self):
        assert _transition_type(1, 0) == "enter_defense"

    def test_expansion_on(self):
        assert _transition_type(1, 2) == "expansion_on"

    def test_expansion_off(self):
        assert _transition_type(2, 1) == "expansion_off"

    def test_no_change(self):
        for s in (0, 1, 2):
            assert _transition_type(s, s) == "rebalance"


class TestOrders:
    def test_defense_to_offense(self):
        current = _target_weights(0)
        target = _target_weights(1)
        orders = _orders(current, target)
        assert len(orders) == 2  # buy BYD, sell 515180
        buy_byd = [o for o in orders if o["asset"] == "BYD"][0]
        assert buy_byd["side"] == "buy"
        assert buy_byd["weight_change"] == pytest.approx(0.25)

    def test_offense_to_expansion(self):
        current = _target_weights(1)
        target = _target_weights(2)
        orders = _orders(current, target)
        assert len(orders) == 2  # buy BYD, sell CASH (borrow)
        buy_byd = [o for o in orders if o["asset"] == "BYD"][0]
        assert buy_byd["side"] == "buy"
        assert buy_byd["weight_change"] == pytest.approx(0.10)

    def test_no_change(self):
        w = _target_weights(1)
        orders = _orders(w, w)
        assert len(orders) == 0


# ---------------------------------------------------------------------------
# Signal alert tests
# ---------------------------------------------------------------------------

class TestBuildSignalAlert:
    def test_no_alert_when_no_previous_state(self):
        obs = _mock_shadow_obs()
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(), previous_state=None)
        assert alert["should_alert"] is False

    def test_alert_on_state_change(self):
        obs = _mock_shadow_obs(base_target=1.0)
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert alert["should_alert"] is True
        assert alert["target_state"] == 2
        assert alert["transition_type"] == "expansion_on"

    def test_no_alert_when_state_unchanged(self):
        obs = _mock_shadow_obs(base_target=1.0)
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=False), previous_state=1)
        assert alert["should_alert"] is False

    def test_no_alert_when_not_eligible(self):
        obs = _mock_shadow_obs(eligible=False)
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert alert["should_alert"] is False

    def test_fingerprint_deterministic(self):
        obs = _mock_shadow_obs()
        a1 = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        a2 = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert a1["fingerprint"] == a2["fingerprint"]

    def test_fingerprint_differs_on_different_state(self):
        obs = _mock_shadow_obs(base_target=0.75)
        a1 = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(), previous_state=1)
        obs2 = _mock_shadow_obs(base_target=1.0)
        a2 = build_byd_signal_alert(obs2, _mock_paired_obs(), _mock_expansion_obs(), previous_state=1)
        assert a1["fingerprint"] != a2["fingerprint"]

    def test_markdown_contains_fingerprint(self):
        obs = _mock_shadow_obs()
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert f"signal-fingerprint:{alert['fingerprint']}" in alert["markdown"]

    def test_telegram_under_limit(self):
        obs = _mock_shadow_obs()
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert len(alert["telegram_text"]) <= 4096

    def test_all_state_labels_exist(self):
        for s in range(3):
            assert s in STATE_LABELS

    def test_all_transition_labels_exist(self):
        for t in ["enter_defense", "enter_offense", "expansion_on", "expansion_off", "rebalance"]:
            assert t in TRANSITION_LABELS

    def test_defense_signal_no_expansion(self):
        obs = _mock_shadow_obs(base_target=0.75)
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=0)
        assert alert["target_state"] == 0  # stays in defense
        assert alert["should_alert"] is False

    def test_expansion_requires_eligible_open(self):
        obs = _mock_shadow_obs(base_target=1.0, eligible=False)
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        assert alert["should_alert"] is False
        assert alert["open_research_eligible"] is False

    def test_json_roundtrip(self):
        obs = _mock_shadow_obs()
        alert = build_byd_signal_alert(obs, _mock_paired_obs(), _mock_expansion_obs(active=True), previous_state=1)
        encoded = json.dumps(alert, ensure_ascii=False, sort_keys=True)
        decoded = json.loads(encoded)
        assert decoded["fingerprint"] == alert["fingerprint"]
        assert decoded["target_state"] == alert["target_state"]
