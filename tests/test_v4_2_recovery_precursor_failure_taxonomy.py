from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_recovery_precursor_failure_taxonomy import (
    _first_transition,
    _shock_memory_context,
    _state_run_context,
    diagnostic_decision,
    feature_separation_analysis,
)


def test_state_run_context_reports_age_and_previous_state() -> None:
    states = pd.Series([0, 1, 1, 1, 2])
    age, previous = _state_run_context(states, 3, target_state=1)
    assert age == 3
    assert previous == 0


def test_shock_memory_context_uses_only_prior_rows() -> None:
    daily = pd.DataFrame(
        {
            "shock_drawdown_now": [-0.02, -0.11, -0.05, -0.03, -0.20],
        }
    )
    age, remaining = _shock_memory_context(
        daily,
        signal_position=3,
        trigger_drawdown=0.10,
        memory_sessions=63,
    )
    assert age == 2
    assert remaining == 61


def test_first_transition_distinguishes_reversion() -> None:
    states = pd.Series([1, 1, 0, 0, 2])
    state_2, state_0, outcome = _first_transition(states, 0, horizon=5)
    assert state_2 == 4
    assert state_0 == 2
    assert outcome == "state0_before_state2"


def _contract() -> dict:
    return {
        "analysis": {
            "pre_execution_numeric_features": ["feature_a", "feature_b"],
        },
        "validation": {
            "minimum_event_count": 4,
            "minimum_failed_event_count": 2,
            "minimum_stable_feature_count": 1,
            "minimum_loo_direction_stability": 0.75,
            "minimum_pairwise_distance_from_half": 0.10,
            "maximum_candidate_monitor_features": 3,
        },
    }


def _taxonomy() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d", "e", "f"],
            "chronological_segment": [
                "early",
                "early",
                "early",
                "early",
                "late",
                "late",
            ],
            "marginal_success": [True, True, False, False, True, True],
            "feature_a": [4.0, 5.0, 1.0, 2.0, 6.0, 7.0],
            "feature_b": [1.0, 3.0, 2.0, 2.0, 4.0, 4.0],
            "failure_type": [
                "successful_recovery",
                "successful_recovery",
                "failed",
                "failed",
                "successful_recovery",
                "successful_recovery",
            ],
        }
    )


def test_feature_separation_is_descriptive_not_predictive() -> None:
    separation, leave_one_out = feature_separation_analysis(_taxonomy(), _contract())
    row = separation.set_index("feature").loc["feature_a"]
    assert bool(row["same_direction_full_and_early"])
    assert bool(row["descriptively_stable"])
    assert not leave_one_out.empty


def test_late_class_imbalance_blocks_new_rule() -> None:
    taxonomy = _taxonomy()
    separation, _ = feature_separation_analysis(taxonomy, _contract())
    decision = diagnostic_decision(taxonomy, separation, _contract())
    assert decision["prospective_feature_monitoring_justified"]
    assert not decision["new_preregistered_trading_hypothesis_justified"]
    assert decision["decision"] == "monitor_features_prospectively_without_new_rule"


def test_missing_feature_is_rejected() -> None:
    contract = _contract()
    contract["analysis"]["pre_execution_numeric_features"].append("missing")
    with pytest.raises(ValueError, match="missing configured features"):
        feature_separation_analysis(_taxonomy(), contract)
