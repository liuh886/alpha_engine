"""Issue #966 Phase 1 contract tests for volume/stat mechanism research."""

from __future__ import annotations

from src.factors.library import load_factor_library
from src.factors.sets.qlib_alpha158 import load_alpha158_definitions

LIBRARY_PATH = "configs/factor_libraries/volume_stat_research.yaml"


def test_phase1_adds_only_one_genuinely_new_canonical_definition() -> None:
    library = load_factor_library(LIBRARY_PATH)

    assert library.catalog.catalog_id == "volume_stat_research"
    assert list(library.groups) == ["signed_volume_flow"]
    assert len(library.catalog.definitions) == 1

    definition = library.factor("volume_stat_research.signed_volume_balance_10d")
    assert definition.information_family == "volume_flow"
    assert definition.required_fields == ("close", "volume")
    assert definition.markets == ("us", "cn")
    assert definition.minimum_lookback == 10
    assert definition.status == "candidate"
    assert definition.source_reference == "docs/research/quantskills_volume_stat_alpha_review.md"
    assert definition.expression == (
        "Sum(Sign($close-Ref($close,1))*$volume,10)/(Mean($volume,10)+1e-12)"
    )


def test_phase1_definition_identity_is_deterministic() -> None:
    first = load_factor_library(LIBRARY_PATH).factor(
        "volume_stat_research.signed_volume_balance_10d"
    )
    second = load_factor_library(LIBRARY_PATH).factor(
        "volume_stat_research.signed_volume_balance_10d"
    )

    assert first.implementation_hash == second.implementation_hash
    assert first.implementation_hash == first.compute_implementation_hash()


def test_existing_alpha158_definitions_are_reused_for_two_first_wave_mechanisms() -> None:
    alpha158 = {row.factor_id: row for row in load_alpha158_definitions()}

    assert "qlib_alpha158.cord10" in alpha158
    assert "qlib_alpha158.rank20" in alpha158
    assert alpha158["qlib_alpha158.cord10"].namespace == "qlib_alpha158"
    assert alpha158["qlib_alpha158.rank20"].namespace == "qlib_alpha158"

    native_ids = {
        row.factor_id
        for row in load_factor_library(LIBRARY_PATH).catalog.definitions
    }
    assert native_ids.isdisjoint({"qlib_alpha158.cord10", "qlib_alpha158.rank20"})
