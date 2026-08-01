from qlib.contrib.data.loader import Alpha158DL

from scripts.factors.build_factor_catalog import build_catalog
from src.factors.sets.qlib_alpha158 import (
    ALPHA158_CONFIG,
    load_alpha158_definitions,
)


def test_alpha158_exact_count_order_and_expression_parity() -> None:
    fields, names = Alpha158DL.get_feature_config(ALPHA158_CONFIG)
    definitions = load_alpha158_definitions()

    assert len(definitions) == 158
    assert [row.display_name for row in definitions] == list(names)
    assert [row.expression for row in definitions] == list(fields)
    assert len({row.factor_id for row in definitions}) == 158
    assert definitions[0].factor_id == "qlib_alpha158.kmid"


def test_alpha158_has_no_alpha161_alias() -> None:
    definitions = load_alpha158_definitions()

    assert all("alpha161" not in row.factor_id for row in definitions)
    assert all(row.namespace == "qlib_alpha158" for row in definitions)


def test_alpha158_definitions_bind_adjusted_ohlcv_semantics() -> None:
    definitions = load_alpha158_definitions()

    assert all(row.markets == ("us", "cn") for row in definitions)
    assert all(row.adjustment_requirement == "adjusted" for row in definitions)
    assert all(row.availability_lag_sessions == 0 for row in definitions)
    assert all(row.status == "unvalidated_formula" for row in definitions)
    assert all("vwap" in row.required_fields for row in definitions)


def test_alpha158_implementation_hashes_are_deterministic() -> None:
    first = load_alpha158_definitions()
    second = load_alpha158_definitions()

    assert [row.implementation_hash for row in first] == [
        row.implementation_hash for row in second
    ]
    assert all(
        row.implementation_hash == row.compute_implementation_hash()
        for row in first
    )


def test_factor_catalog_is_exact_and_not_promoted() -> None:
    catalog = build_catalog()
    payload = catalog.to_dict()

    assert payload["catalog_id"] == "alpha_engine_factor_catalog"
    assert payload["factor_count"] == 158
    assert len(payload["implementation_hash"]) == 64
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert {
        row["status"] for row in payload["definitions"]
    } == {"unvalidated_formula"}
