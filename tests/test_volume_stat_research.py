"""Issue #966 Phase 1 contract tests for volume/stat mechanism research."""

from __future__ import annotations

from src.factors.sets.qlib_alpha158 import load_alpha158_definitions
from src.factors.sets.volume_stat_research import (
    SOURCE_REFERENCE,
    load_volume_stat_research_definitions,
)


def test_phase1_adds_only_one_genuinely_new_native_definition() -> None:
    definitions = load_volume_stat_research_definitions()

    assert len(definitions) == 1
    definition = definitions[0]
    assert definition.factor_id == "volume_stat_research.signed_volume_balance_10d"
    assert definition.information_family == "volume_flow"
    assert definition.required_fields == ("close", "volume")
    assert definition.markets == ("us", "cn")
    assert definition.minimum_lookback == 11
    assert definition.status == "unvalidated_formula"
    assert definition.source_reference == SOURCE_REFERENCE
    assert definition.expression == (
        "Sum(Sign($close-Ref($close,1))*$volume,10)/(Mean($volume,10)+1e-12)"
    )


def test_phase1_definition_identity_is_deterministic_and_past_only() -> None:
    first = load_volume_stat_research_definitions()[0]
    second = load_volume_stat_research_definitions()[0]

    assert first.implementation_hash == second.implementation_hash
    assert first.implementation_hash == first.compute_implementation_hash()
    normalized = first.expression.replace(" ", "")
    assert "Ref($close,-" not in normalized
    assert "Ref($volume,-" not in normalized


def test_existing_alpha158_definitions_are_reused_for_two_first_wave_mechanisms() -> None:
    alpha158 = {row.factor_id: row for row in load_alpha158_definitions()}

    assert "qlib_alpha158.cord10" in alpha158
    assert "qlib_alpha158.rank20" in alpha158
    assert alpha158["qlib_alpha158.cord10"].namespace == "qlib_alpha158"
    assert alpha158["qlib_alpha158.rank20"].namespace == "qlib_alpha158"

    native_ids = {
        row.factor_id for row in load_volume_stat_research_definitions()
    }
    assert native_ids.isdisjoint({"qlib_alpha158.cord10", "qlib_alpha158.rank20"})
