"""Tests for canonical factor definitions and the separate exploratory pool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.factors.exploratory_pool import load_exploratory_factor_pool
from src.factors.library import (
    FACTOR_LIBRARY_SCHEMA_VERSION,
    factor_groups_to_ranker_feature_groups,
    load_factor_library,
)


MINIMAL_LIBRARY = """\
schema_version: "2.0"
catalog:
  id: test_catalog
  version: "1.0"
defaults:
  namespace: test
  factor_version: "1.0"
  source_name: unit-test
  source_version: "1.0"
  source_reference: tests/test_factor_library.py
  availability_lag_sessions: 0
  adjustment_requirement: adjusted
  output_frequency: day
  output_dtype: float64
  missing_value_policy: preserve_nan_after_warmup
  status: unvalidated_formula
factors:
  test.ret5:
    display_name: ret5
    information_family: momentum
    expression: "$close/Ref($close,5)-1"
    required_fields: [close]
    markets: [us, cn]
    minimum_lookback: 5
  test.ret10:
    display_name: ret10
    information_family: momentum
    expression: "$close/Ref($close,10)-1"
    required_fields: [close]
    markets: [us, cn]
    minimum_lookback: 10
groups:
  momentum:
    description: Momentum
    factor_ids: [test.ret5, test.ret10]
  baseline:
    description: Baseline
    factor_ids: [test.ret10]
"""


def _temporary_yaml(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    handle.write(content)
    handle.close()
    return Path(handle.name)


def test_load_select_resolve_and_manifest() -> None:
    path = _temporary_yaml(MINIMAL_LIBRARY)
    try:
        library = load_factor_library(path)
        selected = library.select_groups(["momentum"])
        ranker_groups = factor_groups_to_ranker_feature_groups(selected)
        manifest = library.manifest(["momentum"])

        assert library.schema_version == FACTOR_LIBRARY_SCHEMA_VERSION
        assert ranker_groups[0].expressions == (
            "$close/Ref($close,10)-1",
            "$close/Ref($close,5)-1",
        )
        assert manifest["factor_count"] == 2
        assert manifest["group_count"] == 1
        assert library.resolve_expressions(["test.ret10"]) == [
            "$close/Ref($close,10)-1"
        ]
    finally:
        path.unlink()


def test_group_reuses_definition_instead_of_redefining_it() -> None:
    path = _temporary_yaml(MINIMAL_LIBRARY)
    try:
        library = load_factor_library(path)
        momentum = library["momentum"].factors[1]
        baseline = library["baseline"].factors[0]
        assert momentum is baseline
        assert momentum.factor_id == "test.ret10"
    finally:
        path.unlink()


def test_duplicate_expression_under_two_ids_fails_closed() -> None:
    duplicate = MINIMAL_LIBRARY.replace(
        "groups:\n",
        "  test.ret5_copy:\n"
        "    display_name: duplicate\n"
        "    information_family: momentum\n"
        "    expression: \"$close/Ref($close,5)-1\"\n"
        "    required_fields: [close]\n"
        "    markets: [us, cn]\n"
        "    minimum_lookback: 5\n"
        "groups:\n",
    )
    path = _temporary_yaml(duplicate)
    try:
        with pytest.raises(ValueError, match="same expression more than once"):
            load_factor_library(path)
    finally:
        path.unlink()


def test_unknown_group_and_factor_fail_closed() -> None:
    path = _temporary_yaml(MINIMAL_LIBRARY)
    try:
        library = load_factor_library(path)
        with pytest.raises(ValueError, match="not found"):
            library.select_groups(["missing"])
        with pytest.raises(ValueError, match="unknown factor id"):
            library.resolve_expressions(["missing"])
    finally:
        path.unlink()


def test_only_one_canonical_ohlcv_library_is_required() -> None:
    library = load_factor_library("configs/factor_libraries/ohlcv.yaml")
    assert library.catalog.catalog_id == "alpha_engine_ohlcv"
    assert len(library.catalog.definitions) == 24
    assert "momentum_volatility_volume" in library
    assert "cn_balanced_ohlcv" in library

    expressions = [row.expression for row in library.catalog.definitions]
    assert len(expressions) == len(set(expressions))
    assert library["momentum_volatility_volume"].factor_ids == (
        "ohlcv.momentum.ret_5d",
        "ohlcv.momentum.ret_10d",
        "ohlcv.momentum.ret_20d",
        "ohlcv.volatility.std_ret_10d",
        "ohlcv.volatility.std_ret_20d",
        "ohlcv.volume.momentum_10d",
        "ohlcv.liquidity.volume_vs_ma_20d",
    )


def test_exploratory_pool_has_no_generated_fallback() -> None:
    pool = load_exploratory_factor_pool("configs/factor_pool.yaml")
    assert len(pool) >= 200
    names = {row["name"] for row in pool}
    assert "technical_rsi_proxy_10" in names

    with pytest.raises(FileNotFoundError):
        load_exploratory_factor_pool("configs/does-not-exist.yaml")
