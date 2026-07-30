from pathlib import Path

import yaml


SPEC_PATH = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_focus_universe_source_is_the_user_predeclared_inline_contract() -> None:
    universe = _spec()["universe"]
    assert universe["source"] == "user_predeclared_inline_2026-07-30"
    assert universe["membership_mode"] == "fixed_predeclared"
    assert universe["silent_exclusion_allowed"] is False


def test_validation_execution_assumptions_are_frozen_before_real_results() -> None:
    assumptions = _spec()["evaluation"]["execution_assumptions"]
    assert assumptions == {
        "signal_observation": "daily_close",
        "execution_price": "next_session_open",
        "return_basis": "next_open_to_following_open",
        "forward_return_basis": "next_open_to_horizon_open",
        "state_exposure": {
            "WATCH": 0.0,
            "ENTER": 1.0,
            "HOLD": 1.0,
            "REDUCE": 0.5,
            "EXIT": 0.0,
        },
        "cost_bps_per_unit_exposure_change": 10,
        "false_exit_reentry_sessions": 20,
        "combined_book_weighting": "risk_unit_normalized_equal_weight",
    }


def test_validation_breadth_gates_are_predeclared() -> None:
    targets = _spec()["evaluation"]["development_targets"]
    assert targets["positive_strategy_return_symbol_ratio_min"] == 0.60
    assert targets["positive_qqq_relative_symbol_ratio_min"] == 0.50
    assert targets["minimum_supported_market_regimes"] == 3
    assert targets["maximum_single_symbol_profit_contribution"] == 0.40
