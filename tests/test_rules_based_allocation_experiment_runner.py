from pathlib import Path

import pandas as pd

from src.research.byd_v1_3_candidate import (
    V13_BEAR_DEFENSE_BYD,
    _stateful_min_hold,
    build_v13_signals,
)
from src.research.rules_based_allocation_experiment_runner import (
    run_rules_based_allocation_experiment,
)

SPEC = Path(
    "configs/research_experiments/"
    "byd_v1_3_min_hold_bear_defense_certification_v1.yaml"
)
CURRENT_BUNDLE_ID = (
    "a28519df32797e0a135736e8626b6cf1fb9a1ba950d01248bc48a45b7fc540f9"
)


def test_min_hold_counts_only_eligible_sessions() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="D")
    entry = pd.Series([True, False, False, False, False], index=index)
    exit_ = pd.Series([False, True, True, True, True], index=index)
    eligible = pd.Series([True, False, True, True, True], index=index)

    state = _stateful_min_hold(entry, exit_, eligible, min_hold=2)

    assert state.tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]


def test_v13_state_is_initialized_before_overlap_reindex() -> None:
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    full = pd.DataFrame(
        {
            "close": [2.0, 2.0, 1.0, 1.0],
            "sma_120": [1.0, 1.0, 2.0, 2.0],
            "mom_20": [0.1, 0.1, -0.1, -0.1],
            "mom_60": [0.1, 0.1, 0.1, 0.1],
            "market_state": ["bull", "bull", "sideways", "sideways"],
            "open_research_eligible": [True, True, True, True],
        },
        index=index,
    )

    signals = build_v13_signals(full, target_index=index[-2:])

    assert signals["base_risk_on"].tolist() == [1.0, 1.0]
    assert signals["base_byd_weight"].tolist() == [1.0, 1.0]


def test_bear_defense_uses_frozen_weight() -> None:
    index = pd.date_range("2020-01-01", periods=2, freq="D")
    full = pd.DataFrame(
        {
            "close": [1.0, 1.0],
            "sma_120": [2.0, 2.0],
            "mom_20": [-0.1, -0.1],
            "mom_60": [-0.1, -0.1],
            "market_state": ["bear", "bear"],
            "open_research_eligible": [True, True],
        },
        index=index,
    )

    signals = build_v13_signals(full)

    assert signals["base_byd_weight"].tolist() == [
        V13_BEAR_DEFENSE_BYD,
        V13_BEAR_DEFENSE_BYD,
    ]


def test_byd_v13_certification_runs_offline_against_formal_trace() -> None:
    receipt = run_rules_based_allocation_experiment(SPEC)

    assert receipt["status"] == "completed"
    assert receipt["decision"] in {
        "historically_supported_challenger",
        "not_supported",
    }
    assert receipt["promotion_authorized"] is False
    assert receipt["fresh_holdout"] is False
    assert receipt["historical_evidence_consumed"] is True
    assert receipt["baseline"]["bundle_id"] == CURRENT_BUNDLE_ID
    assert receipt["baseline_trace_reproduction"]["exact"] is True
    assert receipt["gates"]["baseline_identity_and_trace"] is True
    assert receipt["governance"]["prospective_confirmation_required"] is True
