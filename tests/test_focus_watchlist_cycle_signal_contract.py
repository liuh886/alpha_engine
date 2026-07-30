from pathlib import Path

import yaml


SPEC_PATH = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")
EXPECTED_SYMBOLS = [
    "POET",
    "IREN",
    "HIMS",
    "BE",
    "CRDO",
    "HIMX",
    "NBIS",
    "TSLA",
    "CRCL",
]
EXPECTED_STATES = ["WATCH", "ENTER", "HOLD", "REDUCE", "EXIT"]


def _load_spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_focus_watchlist_is_fixed_and_benchmark_is_not_a_candidate() -> None:
    spec = _load_spec()
    universe = spec["universe"]

    assert universe["membership_mode"] == "fixed_predeclared"
    assert universe["symbols"] == EXPECTED_SYMBOLS
    assert len(universe["symbols"]) == len(set(universe["symbols"]))
    assert "QQQ" not in universe["symbols"]
    assert universe["benchmark_symbols"] == ["QQQ"]
    assert universe["silent_exclusion_allowed"] is False


def test_signal_is_one_shared_per_security_state_machine() -> None:
    spec = _load_spec()
    signal = spec["signal"]

    assert spec["objective"]["cross_sectional_ranking"] is False
    assert signal["family"] == "per_security_time_series_state_machine"
    assert signal["shared_rule_set_across_symbols"] is True
    assert signal["states"] == EXPECTED_STATES
    assert signal["evaluation_time"] == "daily_close"
    assert signal["execution_time"] == "next_trading_session"


def test_v1_parameters_and_manual_execution_boundary_are_frozen() -> None:
    spec = _load_spec()
    signal = spec["signal"]
    risk = spec["risk"]
    execution = spec["execution"]
    search = spec["parameter_search"]

    assert signal["market_regime"]["medium_trend_days"] == 50
    assert signal["market_regime"]["long_trend_days"] == 200
    assert signal["security_trend"]["medium_trend_days"] == 50
    assert signal["security_trend"]["long_trend_days"] == 100
    assert signal["security_trend"]["relative_momentum_days"] == 63
    assert signal["security_trend"]["breakout_days"] == 20
    assert signal["security_trend"]["atr_days"] == 20
    assert signal["security_trend"]["trailing_stop_atr_multiple"] == 3.0

    assert risk["manual_execution_only"] is True
    assert risk["automatic_order_routing"] is False
    assert risk["shorting_allowed"] is False
    assert risk["tier_changes_signal_formula"] is False
    assert set(risk["symbol_tiers"]) == set(EXPECTED_SYMBOLS)
    assert execution["broker_integration"] is False
    assert execution["output_mode"] == "manual_trade_ticket"

    assert search == {
        "allowed": False,
        "per_symbol_fitting_allowed": False,
        "threshold_grid_allowed": False,
        "lookback_grid_allowed": False,
        "state_rule_variants_allowed": False,
    }


def test_evidence_ledger_reserves_2026h2_before_validation() -> None:
    spec = _load_spec()
    evidence = spec["evidence"]

    assert evidence["development_observed"] == {
        "start": "2021-01-01",
        "end": "2025-12-31",
    }
    assert evidence["falsification_only"] == {
        "start": "2026-01-01",
        "end": "2026-06-30",
    }
    assert evidence["independent_reserved"]["start"] == "2026-07-01"
    assert evidence["independent_reserved"]["end"] == "2026-12-31"
    assert (
        evidence["independent_reserved"]["opening_rule"]
        == "complete_half_year_plus_20_session_forward_horizon"
    )
