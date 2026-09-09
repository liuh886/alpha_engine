"""Pool/strategy/reference lists must agree with provider auxiliaries.

Regression gate for the CN_27 outage class: strategy files changed without
updating the hand-written auxiliary tuples, so the shared provider missed
bars and the formal refresh failed closed at runtime. These tests fail at
PR time instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.data.refresh_selected_pool_prices_v2 import (
    COMPARISON_REFERENCE_AUXILIARIES,
    FORMAL_MARKET_AUXILIARIES,
)
from src.artifacts.formal_provider_cache import DEFAULT_AUXILIARIES
from src.governance.auxiliary_derivation import (
    STRATEGY_SOURCES,
    derive_required_auxiliaries,
    normalize_symbol,
    verify_against_hardcoded,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str):
    return yaml.safe_load((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))


def test_cn_27_overlap_and_exceptions_match_selected_pool():
    pool = _load("configs/pools/cn_all_weather_alpha_rotation_v1.yaml")
    universe = _load("configs/research_universes/cn_selected_equities_v3.yaml")
    strategy = {normalize_symbol(entry["symbol"]) for entry in pool["symbols"]}
    selected = {normalize_symbol(value) for value in universe["symbols"]}
    governance = pool["governance"]
    assert len(strategy) == int(pool["candidate_count"]) == 27
    assert governance["selected_pool_overlap_count"] == len(strategy & selected) == 22
    assert sorted(strategy - selected) == sorted(
        normalize_symbol(value)
        for value in governance["strategy_specific_exceptions"]
    )


def test_cn_27_model_declared_counts_match_pool_file():
    model = _load("configs/models/cn_27_v1_3.yaml")
    pool = _load("configs/pools/cn_all_weather_alpha_rotation_v1.yaml")
    universe = model["universe"]
    assert universe["source"] == "configs/pools/cn_all_weather_alpha_rotation_v1.yaml"
    assert int(universe["declared_candidate_count"]) == int(pool["candidate_count"])
    assert int(universe["selected_pool_overlap_count"]) == int(
        pool["governance"]["selected_pool_overlap_count"]
    )


def test_derived_auxiliaries_are_covered_by_hardcoded_tuples():
    combined = {
        market: tuple(
            list(FORMAL_MARKET_AUXILIARIES[market])
            + list(COMPARISON_REFERENCE_AUXILIARIES.get(market, ()))
        )
        for market in FORMAL_MARKET_AUXILIARIES
    }
    report = verify_against_hardcoded(DEFAULT_AUXILIARIES, REPOSITORY_ROOT)
    combined_report = verify_against_hardcoded(combined, REPOSITORY_ROOT)
    for market in ("us", "cn"):
        assert report[market]["missing"] == [], market
        assert report[market]["undeclared_extras"] == [], market
        assert combined_report[market]["missing"] == [], market
        assert combined_report[market]["undeclared_extras"] == [], market


def test_derived_cn_auxiliaries_have_strategy_provenance():
    derived = derive_required_auxiliaries(REPOSITORY_ROOT)["cn"]
    assert sorted(derived.required) == [
        "002156",
        "002281",
        "300274",
        "515180",
        "601939",
        "688183",
    ]
    assert derived.provenance["515180"].endswith(":references")
    assert derived.provenance["002156"].endswith(":pool_members")
    assert "000300" in derived.excluded  # benchmark, never fetched as auxiliary


def test_strategy_source_files_are_cache_contract_inputs():
    from src.artifacts.formal_provider_cache import CONTRACT_PATHS

    for sources in STRATEGY_SOURCES.values():
        for source in sources:
            if source["kind"] in ("strategy_pool", "strategy_bundle"):
                assert str(source["path"]) in CONTRACT_PATHS
