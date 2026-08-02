from __future__ import annotations

import re

import numpy as np
import pandas as pd

from src.research.v4_2_prospective_evidence_ledger import (
    EVENT_MARKER_PREFIX,
    build_candidate_event_records,
    build_monthly_summary,
    compute_event_observation,
    decode_marker_payload,
    encode_marker,
    recovery_precursor_boolean,
    render_event_issue_body,
    validate_event_record,
)


def _summary(*, current_state: int = 1, target_state: int = 1) -> dict:
    return {
        "latest_data_date": "2026-08-03",
        "data_identity": {
            "mode": "governed_bundle",
            "bundle_id": "fixture-bundle",
            "selected_providers": {"QQQ": "fixture"},
        },
        "bridge_latest_snapshot": {
            "latest_executed_position": {
                "economic_date": "2026-08-03",
                "position_state": current_state,
                "state_entry_date": "2026-08-01",
                "state_age_sessions": 3,
                "weights": {
                    "QQQI": 0.5 if current_state == 1 else 0.0,
                    "QQQ": 0.5 if current_state == 1 else 0.25,
                    "TQQQ": 0.0 if current_state == 1 else 0.75,
                },
            },
            "latest_close_signal": {
                "signal_date": "2026-08-03",
                "decision_state": target_state,
                "decision_reason": "fixture_reason",
                "price_context": {
                    "qqq_close": 500.0,
                    "qqq_vs_ma20": 0.025,
                    "shock_memory": True,
                    "medium_repair": True,
                },
                "volatility_context": {
                    "vix_close": 17.0,
                    "vix_return_5d": -0.2,
                    "vix_normalized": True,
                    "vxn_close": 22.0,
                    "vxn_return_1d": -0.05,
                    "vxn_return_5d": -0.18,
                    "vxn_retreat_from_peak": -0.25,
                    "vxn_stress": False,
                },
            },
        },
    }


def _alert(*, should_alert: bool = False, target_state: int = 1) -> dict:
    target = (
        {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0}
        if target_state == 1
        else {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75}
    )
    return {
        "experiment_id": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "should_alert": should_alert,
        "data_freshness_ok": True,
        "fingerprint": "fixture-fingerprint",
        "transition_type": "add_tqqq_leverage",
        "target_weights": target,
        "turnover_units": 1.0,
        "estimated_transaction_cost": 0.001,
        "markdown": "## Fixture alert\n",
    }


def _daily() -> pd.DataFrame:
    dates = pd.bdate_range("2026-08-04", periods=10)
    qqq = np.array([0.01, -0.005, 0.006, 0.002, -0.001, 0.004, 0.003, -0.002, 0.005, 0.001])
    tqqq = np.array([0.03, -0.016, 0.018, 0.006, -0.004, 0.012, 0.009, -0.006, 0.015, 0.003])
    opens = 500.0 * np.cumprod(np.r_[1.0, 1.0 + qqq[:-1]])
    closes = opens * (1.0 + qqq * 0.6)
    return pd.DataFrame(
        {
            "date": dates,
            "QQQ_next_open_return": qqq,
            "TQQQ_next_open_return": tqqq,
            "QQQ_open": opens,
            "QQQ_close": closes,
            "TQQQ_open": 50.0 * np.cumprod(np.r_[1.0, 1.0 + tqqq[:-1]]),
            "QQQI_open": opens * 0.1,
            "position_state": [1, 1, 1, 2, 2, 2, 2, 2, 2, 2],
        }
    )


def test_precursor_record_is_created_once_and_is_non_actionable() -> None:
    summary = _summary()
    alert = _alert()
    assert recovery_precursor_boolean(summary)

    records = build_candidate_event_records(summary, alert)
    assert len(records) == 1
    record = records[0]
    assert record["event_type"] == "recovery_precursor"
    assert record["actionable"] is False
    assert record["shadow_allocations"]["tqqq_50"]["TQQQ"] == 0.5
    validate_event_record(record)

    existing = [{"record": record, "latest_status": "active_precursor"}]
    assert build_candidate_event_records(summary, alert, existing) == []


def test_state_change_record_uses_fresh_alert_and_not_precursor() -> None:
    summary = _summary(current_state=1, target_state=2)
    records = build_candidate_event_records(
        summary,
        _alert(should_alert=True, target_state=2),
    )
    assert len(records) == 1
    assert records[0]["event_type"] == "state_change"
    assert records[0]["target_weights"]["TQQQ"] == 0.75
    assert not records[0]["recovery_precursor_boolean"]


def test_marker_round_trip_and_issue_body_contains_fingerprint() -> None:
    record = build_candidate_event_records(
        _summary(current_state=1, target_state=2),
        _alert(should_alert=True, target_state=2),
    )[0]
    marker = encode_marker(EVENT_MARKER_PREFIX, record)
    encoded = re.search(r"prospective-evidence-record:([^ ]+)", marker)
    assert encoded is not None
    assert decode_marker_payload(encoded.group(1)) == record

    body = render_event_issue_body(record, alert_markdown="## Alert")
    assert "signal-fingerprint:fixture-fingerprint" in body
    assert EVENT_MARKER_PREFIX in body


def test_observation_adds_only_available_horizons_and_reconciles_attribution() -> None:
    record = build_candidate_event_records(_summary(), _alert())[0]
    observation = compute_event_observation(
        record,
        _daily(),
        current_precursor_boolean=False,
        latest_data_date="2026-08-17",
        posted_horizons=[1, 2, 3],
        latest_status="active_precursor",
    )
    assert observation["completed_horizons"] == [1, 2, 3, 5, 10]
    assert observation["new_horizons"] == [5, 10]
    assert observation["status"] == "observing_outcomes"
    assert observation["status_changed"]
    assert observation["time_to_formal_state_2_sessions"] == 4
    assert observation["execution"]["execution_date"] == "2026-08-04"

    five = observation["outcomes"]["5"]
    reconciled = (
        five["directional_leverage_component"]
        + five["tracking_compounding_component"]
    )
    assert np.isclose(reconciled, five["raw_50_vs_25_component"])
    assert five["qqq_mfe"] is not None
    assert five["qqq_mae"] is not None


def test_monthly_summary_never_authorizes_model_change() -> None:
    record = build_candidate_event_records(_summary(), _alert())[0]
    observation = compute_event_observation(
        record,
        _daily(),
        current_precursor_boolean=False,
        latest_data_date="2026-08-17",
    )
    summary = build_monthly_summary(
        [{"record": record}],
        [observation],
        "2026-08",
    )
    assert summary["event_count"] == 1
    assert summary["recovery_precursor_event_count"] == 1
    assert summary["completed_horizon_counts"]["10"] == 1
    assert summary["model_change_authorized"] is False
