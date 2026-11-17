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
    FORMAL_MARKET_AUXILIARIES,
    OPTIONAL_REFERENCE_AUXILIARIES,
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
            + list(OPTIONAL_REFERENCE_AUXILIARIES.get(market, ()))
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


def test_sp500_is_a_declared_extra_without_strategy_drift():
    from src.governance.auxiliary_derivation import DECLARED_EXTRAS

    assert "SPX" in DEFAULT_AUXILIARIES["us"]
    assert "SPX" not in DEFAULT_AUXILIARIES["cn"]
    assert "SPX" in DECLARED_EXTRAS["us"]
    derived = derive_required_auxiliaries(REPOSITORY_ROOT)
    assert "SPX" not in derived["us"].required
    assert "SPX" not in derived["us"].excluded
    report = verify_against_hardcoded(DEFAULT_AUXILIARIES, REPOSITORY_ROOT)
    for market in ("us", "cn"):
        assert report[market]["missing"] == [], market
        assert report[market]["undeclared_extras"] == [], market


def test_vix_is_a_declared_us_extra_without_strategy_drift():
    from src.governance.auxiliary_derivation import DECLARED_EXTRAS

    assert "VIX" in DEFAULT_AUXILIARIES["us"]
    assert "VIX" not in DEFAULT_AUXILIARIES["cn"]
    assert "VIX" in DECLARED_EXTRAS["us"]
    citation = DECLARED_EXTRAS["us"]["VIX"]
    assert "2026-11-17" in citation
    assert "reference_instrument_registry_v1.yaml" in citation
    derived = derive_required_auxiliaries(REPOSITORY_ROOT)
    assert "VIX" not in derived["us"].required
    # VIX is a strategy-declared non-executable index reference: derived as
    # excluded, so the hardcoded auxiliary stays an explicit Owner citation.
    assert "non-executable/index reference" in derived["us"].excluded["VIX"]
    report = verify_against_hardcoded(DEFAULT_AUXILIARIES, REPOSITORY_ROOT)
    for market in ("us", "cn"):
        assert report[market]["missing"] == [], market
        assert report[market]["undeclared_extras"] == [], market


def test_optional_reference_class_is_explicit_and_disjoint():
    from src.data.auxiliary_scope import (
        all_governed_auxiliaries,
        optional_reference_auxiliaries,
        required_formal_auxiliaries,
    )

    assert optional_reference_auxiliaries("us") == ("CGDV", "SPX", "VIX")
    assert optional_reference_auxiliaries("cn") == ()
    assert set(required_formal_auxiliaries("us")) == {
        "QQQI", "TQQQ", "SGOV", "TYGO"
    }
    assert not set(required_formal_auxiliaries("us")) & set(
        optional_reference_auxiliaries("us")
    )
    for market in ("us", "cn"):
        assert DEFAULT_AUXILIARIES[market] == all_governed_auxiliaries(market)


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


def test_strategy_vendor_overrides_reproduce_frozen_provenance():
    from src.governance.auxiliary_derivation import (
        strategy_symbol_vendor_overrides,
        strategy_vendor_provenance,
    )

    overrides = strategy_symbol_vendor_overrides(REPOSITORY_ROOT)["cn"]
    assert overrides["301291"] == "akshare_sina"
    assert overrides["000300"] == "akshare"
    assert overrides["515180"] == "tencent_qfq_history"
    assert overrides["002156"] == "tencent_qfq_history"
    # Pins must equal the sealed frozen coverage exactly: every provenance
    # symbol pinned identically, no extras beyond zero-pad aliases.
    provenance = strategy_vendor_provenance(REPOSITORY_ROOT)["cn"]
    canonical = {key: value for key, value in overrides.items() if len(key) == 6}
    assert canonical == provenance
    assert len(overrides) == len(provenance) + 7  # 7 zero-pad aliases


def test_hardened_router_pins_blessed_vendor_first():
    from scripts.data.refresh_selected_pool_prices_v2 import build_hardened_router

    router = build_hardened_router("cn")
    assert router.providers_for_request("cn", "301291")[0] == "akshare_sina"
    assert router.providers_for_request("cn", "000300")[0] == "akshare"
    assert router.providers_for_request("cn", "002156")[0] == "tencent_qfq_history"
    # Pins keep their order; the selected-pool Yahoo quarantine also applies.
    market_chain = router.providers_for_market("cn")
    for symbol in ("301291", "000300"):
        assert sorted(router.providers_for_request("cn", symbol)) == sorted(
            name for name in market_chain if name != "yfinance"
        )
    assert sorted(router.providers_for_request("cn", "002156")) == sorted(market_chain)
    # Unregistered requests keep the market chain; this is not a pool substitute.
    assert router.providers_for_request("cn", "999999") == market_chain
    # US has no strategy provenance: untouched.
    us_router = build_hardened_router("us")
    assert us_router.providers_for_request("us", "AAPL") == ["yfinance"]
