"""Tests for the structured Qlib-free factor library."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.research.factor_library import (
    FactorGroup,
    FactorSpec,
    factor_groups_to_ranker_feature_groups,
    factor_library_manifest,
    load_factor_library,
    resolve_factor_expressions,
    select_factor_groups,
)


MINIMAL_LIBRARY = """\
schema_version: "1.0"
groups:
  momentum:
    description: "Momentum"
    factors:
      - id: "test:ret5"
        expression: "$close/Ref($close,5)-1"
        family: "momentum"
  baselines:
    description: "Baselines"
    factors:
      - id: "factor:test"
        expression: "$close/Ref($close,10)-1"
        family: "baseline"
"""


def _temporary_yaml(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    handle.write(content)
    handle.close()
    return Path(handle.name)


def test_factor_spec_and_group_validate_required_fields() -> None:
    with pytest.raises(ValueError, match="id must be non-empty"):
        FactorSpec(id="", expression="x", family="f")
    with pytest.raises(ValueError, match="expression must be non-empty"):
        FactorSpec(id="x", expression="", family="f")
    factor = FactorSpec(id="x", expression="expr", family="f")
    with pytest.raises(ValueError, match="must contain at least one factor"):
        FactorGroup(name="g", description="", factors=())
    group = FactorGroup(name="g", description="", factors=(factor,))
    assert group.factor_ids == ("x",)


def test_load_select_convert_and_manifest() -> None:
    path = _temporary_yaml(MINIMAL_LIBRARY)
    try:
        library = load_factor_library(path)
        selected = select_factor_groups(library, ["momentum"])
        ranker_groups = factor_groups_to_ranker_feature_groups(selected)
        manifest = factor_library_manifest(selected)
        assert ranker_groups[0].name == "momentum"
        assert ranker_groups[0].expressions == ("$close/Ref($close,5)-1",)
        assert manifest["n_groups"] == 1
        assert manifest["n_factors"] == 1
        assert resolve_factor_expressions(["factor:test"], library) == [
            "$close/Ref($close,10)-1"
        ]
    finally:
        path.unlink()


def test_unknown_group_and_factor_fail_closed() -> None:
    path = _temporary_yaml(MINIMAL_LIBRARY)
    try:
        library = load_factor_library(path)
        with pytest.raises(ValueError, match="not found"):
            select_factor_groups(library, ["missing"])
        with pytest.raises(ValueError, match="Unknown factor id"):
            resolve_factor_expressions(["missing"], library)
    finally:
        path.unlink()


def test_duplicate_factor_ids_fail_closed() -> None:
    path = _temporary_yaml(
        """\
schema_version: "1.0"
groups:
  a:
    description: "a"
    factors:
      - id: "duplicate"
        expression: "$close"
        family: "x"
  b:
    description: "b"
    factors:
      - id: "duplicate"
        expression: "$volume"
        family: "x"
"""
    )
    try:
        with pytest.raises(ValueError, match="Duplicate factor id"):
            load_factor_library(path)
    finally:
        path.unlink()


def test_real_factor_libraries_load_with_unique_ids() -> None:
    for filename in ("cn_ohlcv.yaml", "us_ohlcv.yaml"):
        library = load_factor_library(Path("configs/factor_libraries") / filename)
        all_ids = [factor.id for group in library.values() for factor in group.factors]
        assert len(all_ids) == len(set(all_ids))
        assert "factor_baselines" in library


def test_cn_corrected_formulas_are_versioned() -> None:
    library = load_factor_library("configs/factor_libraries/cn_ohlcv.yaml")
    expressions = {
        factor.id: factor.expression
        for group in library.values()
        for factor in group.factors
    }
    assert expressions["cn:risk_adjusted:ret10_per_vol10:v2"] == (
        "($close/Ref($close,10)-1)/"
        "(Std($close/Ref($close,1)-1,10)+1e-12)"
    )
    assert expressions["cn:pressure:ret1_x_vol_shock_5:v2"] == (
        "($close/Ref($close,1)-1)*($volume/Mean($volume,5)-1)"
    )
    assert "cn:risk_adjusted:ret10_per_vol10" not in expressions
    assert "cn:pressure:ret1_x_vol_shock_5" not in expressions
