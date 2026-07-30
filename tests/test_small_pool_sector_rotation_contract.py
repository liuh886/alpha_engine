from pathlib import Path

import yaml


POOL_PATH = Path("configs/pools/us_small_pool_v1.yaml")
SPEC_PATH = Path("configs/research_paradigms/us_small_pool_sector_rotation_v1.yaml")
EXPECTED_ADDITIONS = {"AAPL", "MSFT", "PDD", "JD", "KO", "WMT"}
EXPECTED_REFERENCES = {"QQQ", "SOX"}
EXPECTED_BASKETS = {
    "semiconductor_compute",
    "optical_networking",
    "ai_infrastructure_power",
    "mega_cap_platforms",
    "china_consumer_internet",
    "defensive_consumer",
    "consumer_growth",
}
EXPECTED_BASELINES = [
    "equal_weight_pool_buy_and_hold",
    "time_series_state_only",
    "hierarchical_cross_section_only",
    "hierarchical_cross_section_plus_state",
]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_pool_is_versioned_unique_and_contains_user_additions() -> None:
    pool = _load(POOL_PATH)
    baskets = pool["baskets"]
    symbols = [symbol for basket in baskets.values() for symbol in basket["symbols"]]

    assert pool["pool_id"] == "us_small_pool_v1"
    assert pool["membership_mode"] == "versioned_predeclared"
    assert pool["primary_basket_only"] is True
    assert pool["silent_exclusion_allowed"] is False
    assert set(baskets) == EXPECTED_BASKETS
    assert len(symbols) == 23
    assert len(symbols) == len(set(symbols))
    assert EXPECTED_ADDITIONS.issubset(symbols)
    assert EXPECTED_REFERENCES.isdisjoint(symbols)
    assert all(len(basket["symbols"]) >= 2 for basket in baskets.values())


def test_pool_changes_require_a_new_predeclared_version() -> None:
    governance = _load(POOL_PATH)["membership_governance"]

    assert governance == {
        "additions_require_new_pool_version": True,
        "removals_require_new_pool_version": True,
        "basket_reclassification_requires_new_pool_version": True,
        "aliases_require_new_pool_version": True,
        "changes_before_performance_review": True,
        "retrospective_removal_allowed": False,
        "short_history_policy": "diagnostic_or_forward_only",
        "delisted_symbol_policy": (
            "retain_historical_membership_and_mark_unavailable_after_last_trade"
        ),
    }


def test_basket_score_is_simple_equal_weight_and_not_fitted() -> None:
    spec = _load(SPEC_PATH)
    rotation = spec["rotation"]
    components = rotation["score"]["components"]

    assert spec["objective"]["model_fitting"] is False
    assert spec["objective"]["cash_allowed"] is True
    assert rotation["rotation_anchor_date"] == "2021-01-04"
    assert rotation["rebalance_every_n_benchmark_sessions"] == 10
    assert rotation["maximum_selected_baskets"] == 2
    assert rotation["maximum_selected_symbols_per_basket"] == 2
    assert rotation["forced_selection"] is False
    assert set(components) == {
        "median_relative_momentum_63_vs_benchmark",
        "median_momentum_20",
        "breadth_above_sma50",
        "median_drawdown_from_63d_high",
    }
    assert sum(component["weight"] for component in components.values()) == 1.0
    assert {component["weight"] for component in components.values()} == {0.25}
    assert all(
        component["direction"] == "higher_is_better"
        for component in components.values()
    )


def test_security_cross_section_is_explicit_and_state_is_absolute_filter() -> None:
    spec = _load(SPEC_PATH)
    architecture = spec["architecture"]
    selection = spec["security_selection"]
    cross_section = selection["cross_section"]
    components = cross_section["components"]

    assert architecture["layers"] == [
        "market_regime",
        "basket_cross_section",
        "security_cross_section",
        "security_timing",
    ]
    assert architecture["cross_market_ranking_allowed"] is False
    assert set(components) == {
        "relative_momentum_63_vs_benchmark",
        "momentum_20",
        "drawdown_from_63d_high",
        "realized_volatility_20",
    }
    assert sum(component["weight"] for component in components.values()) == 1.0
    assert {component["weight"] for component in components.values()} == {0.25}
    assert components["realized_volatility_20"]["direction"] == "lower_is_better"
    assert selection["state_is_absolute_filter_not_primary_rank"] is True
    assert selection["absolute_state_filter"] == {
        "ENTER": 1.0,
        "HOLD": 1.0,
        "REDUCE": 0.5,
        "WATCH": 0.0,
        "EXIT": 0.0,
    }
    assert selection["entry_requires_selected_basket"] is True
    assert selection["daily_reduce_and_exit_between_rotation_dates"] is True


def test_state_machine_formula_is_reused_without_legacy_universe() -> None:
    timing = _load(SPEC_PATH)["architecture"]["security_timing_component"]

    assert timing["formula_source"].endswith(
        "us_focus_watchlist_cycle_signal_v1.yaml"
    )
    assert timing["reuse_scope"] == [
        "market_regime",
        "security_trend",
        "transitions",
    ]
    assert timing["source_universe_reused"] is False
    assert timing["candidate_universe_source"] == "pool_spec.baskets"


def test_attribution_baselines_and_reserved_evidence_are_frozen() -> None:
    spec = _load(SPEC_PATH)
    evidence = spec["evidence"]

    assert spec["benchmarking"]["baselines"] == EXPECTED_BASELINES
    assert spec["benchmarking"]["require_incremental_attribution"] is True
    assert not any(spec["parameter_search"].values())
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
