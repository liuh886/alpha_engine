"""Tests for structured factor library (FactorSpec, FactorGroup, YAML loading)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.research.factor_library import (
    STRUCTURED_FACTOR_LIBRARY_SCHEMA,
    FactorGroup,
    FactorSpec,
    factor_groups_to_ranker_feature_groups,
    factor_library_manifest,
    load_factor_library,
    resolve_factor_expressions,
    select_factor_groups,
)
from src.research.ranker_calibration_grid import RankerFeatureGroup

# For #91 compatibility checks
from src.research.cn_feature_quality import cn_factor_baseline_expressions, cn_ranker_feature_groups

# ── FactorSpec ───────────────────────────────────────────────────────────────


class TestFactorSpec:
    def test_construction(self) -> None:
        spec = FactorSpec(id="test:family:name", expression="$close/Ref($close,1)-1", family="family")
        assert spec.id == "test:family:name"
        assert spec.expression == "$close/Ref($close,1)-1"
        assert spec.family == "family"
        assert spec.description == ""

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id must be non-empty"):
            FactorSpec(id="", expression="x", family="f")

    def test_empty_expression_raises(self) -> None:
        with pytest.raises(ValueError, match="expression must be non-empty"):
            FactorSpec(id="x", expression="", family="f")

    def test_empty_family_raises(self) -> None:
        with pytest.raises(ValueError, match="family must be non-empty"):
            FactorSpec(id="x", expression="x", family="")

    def test_to_dict(self) -> None:
        spec = FactorSpec(id="a", expression="b", family="c", description="d")
        assert spec.to_dict() == {"id": "a", "expression": "b", "family": "c", "description": "d"}

    def test_frozen(self) -> None:
        spec = FactorSpec(id="x", expression="y", family="z")
        with pytest.raises(Exception):
            spec.id = "new"  # type: ignore[misc]


# ── FactorGroup ──────────────────────────────────────────────────────────────


class TestFactorGroup:
    def test_construction(self) -> None:
        f1 = FactorSpec(id="a", expression="expr_a", family="mom")
        f2 = FactorSpec(id="b", expression="expr_b", family="vol")
        group = FactorGroup(name="g", description="desc", factors=(f1, f2))
        assert group.name == "g"
        assert group.description == "desc"
        assert len(group.factors) == 2
        assert group.factor_ids == ("a", "b")

    def test_empty_name_raises(self) -> None:
        f = FactorSpec(id="a", expression="x", family="f")
        with pytest.raises(ValueError, match="name must be non-empty"):
            FactorGroup(name="", description="", factors=(f,))

    def test_empty_factors_raises(self) -> None:
        with pytest.raises(ValueError, match="must contain at least one factor"):
            FactorGroup(name="g", description="", factors=())

    def test_to_dict(self) -> None:
        f = FactorSpec(id="a", expression="b", family="c")
        group = FactorGroup(name="g", description="d", factors=(f,))
        d = group.to_dict()
        assert d["name"] == "g"
        assert len(d["factors"]) == 1
        assert d["factors"][0]["id"] == "a"

    def test_frozen(self) -> None:
        f = FactorSpec(id="a", expression="x", family="f")
        group = FactorGroup(name="g", description="", factors=(f,))
        with pytest.raises(Exception):
            group.name = "new"  # type: ignore[misc]


# ── YAML loading ─────────────────────────────────────────────────────────────


MINIMAL_YAML = """\
schema_version: "1.0"
groups:
  simple:
    description: "Simple group"
    factors:
      - id: "test:mom:ret5"
        expression: "$close/Ref($close,5)-1"
        family: "momentum"
        description: "5-day return"
      - id: "test:vol:std10"
        expression: "Std($close/Ref($close,1)-1,10)"
        family: "volatility"
        description: "10-day vol"
"""


class TestLoadFactorLibrary:
    def test_load_minimal(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(MINIMAL_YAML)
            tmp_path = f.name
        try:
            library = load_factor_library(tmp_path)
            assert isinstance(library, dict)
            assert len(library) == 1
            assert "simple" in library
            group = library["simple"]
            assert group.name == "simple"
            assert len(group.factors) == 2
            assert group.factors[0].id == "test:mom:ret5"
            assert group.factors[1].id == "test:vol:std10"
        finally:
            Path(tmp_path).unlink()

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_factor_library("/nonexistent/path.yaml")

    def test_invalid_schema(self) -> None:
        yaml_content = """\
schema_version: "99.0"
groups:
  x:
    description: "x"
    factors: []
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported factor library schema"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_empty_groups_raises(self) -> None:
        yaml_content = """\
schema_version: "1.0"
groups: {}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="groups.*must be a non-empty mapping"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()


class TestDuplicateIdRejection:
    def test_duplicate_ids_raise(self) -> None:
        yaml_content = """\
schema_version: "1.0"
groups:
  g1:
    description: "group 1"
    factors:
      - id: "dup:id"
        expression: "$close/Ref($close,1)-1"
        family: "mom"
  g2:
    description: "group 2"
    factors:
      - id: "dup:id"
        expression: "$close/Ref($close,5)-1"
        family: "mom"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="Duplicate factor id"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_missing_expression_raises(self) -> None:
        yaml_content = """\
schema_version: "1.0"
groups:
  g:
    description: "g"
    factors:
      - id: "x"
        family: "f"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="empty or missing.*expression"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_missing_id_raises(self) -> None:
        yaml_content = """\
schema_version: "1.0"
groups:
  g:
    description: "g"
    factors:
      - expression: "x"
        family: "f"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="empty or missing.*id"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_duplicate_group_names_raise(self) -> None:
        yaml_content = """\
schema_version: "1.0"
groups:
  g:
    description: "first"
    factors:
      - id: "a"
        expression: "$close"
        family: "mom"
  g:
    description: "second"
    factors:
      - id: "b"
        expression: "$volume"
        family: "vol"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="Duplicate group name"):
                load_factor_library(tmp_path)
        finally:
            Path(tmp_path).unlink()


# ── Group selection (fail closed) ────────────────────────────────────────────


class TestSelectFactorGroups:
    @pytest.fixture
    def sample_library(self) -> dict[str, FactorGroup]:
        f1 = FactorSpec(id="a", expression="$close", family="mom")
        f2 = FactorSpec(id="b", expression="$volume", family="vol")
        f3 = FactorSpec(id="c", expression="$high", family="mom")
        return {
            "group1": FactorGroup(name="group1", description="", factors=(f1, f2)),
            "group2": FactorGroup(name="group2", description="", factors=(f3,)),
        }

    def test_select_existing_groups(self, sample_library) -> None:
        groups = select_factor_groups(sample_library, ["group1", "group2"])
        assert len(groups) == 2
        assert groups[0].name == "group1"
        assert groups[1].name == "group2"

    def test_select_single_group(self, sample_library) -> None:
        groups = select_factor_groups(sample_library, ["group2"])
        assert len(groups) == 1
        assert groups[0].name == "group2"

    def test_select_unknown_group_fails_closed(self, sample_library) -> None:
        with pytest.raises(ValueError, match="FactorGroup 'nonexistent' not found"):
            select_factor_groups(sample_library, ["nonexistent"])


# ── Conversion to RankerFeatureGroup ─────────────────────────────────────────


class TestFactorGroupsToRankerFeatureGroups:
    def test_conversion(self) -> None:
        f1 = FactorSpec(id="z", expression="expr_z", family="f")
        f2 = FactorSpec(id="a", expression="expr_a", family="f")
        group = FactorGroup(name="test", description="", factors=(f1, f2))
        rfgroups = factor_groups_to_ranker_feature_groups([group])
        assert len(rfgroups) == 1
        rfg = rfgroups[0]
        assert isinstance(rfg, RankerFeatureGroup)
        assert rfg.name == "test"
        # Expressions ordered by factor id
        assert rfg.expressions == ("expr_a", "expr_z")

    def test_multiple_groups(self) -> None:
        f1 = FactorSpec(id="a", expression="e_a", family="f")
        f2 = FactorSpec(id="b", expression="e_b", family="f")
        g1 = FactorGroup(name="g1", description="", factors=(f1,))
        g2 = FactorGroup(name="g2", description="", factors=(f2,))
        rfgroups = factor_groups_to_ranker_feature_groups([g1, g2])
        assert len(rfgroups) == 2
        assert rfgroups[0].name == "g1"
        assert rfgroups[1].name == "g2"


# ── Manifest ─────────────────────────────────────────────────────────────────


class TestFactorLibraryManifest:
    def test_manifest(self) -> None:
        f = FactorSpec(id="a", expression="b", family="c")
        groups = [FactorGroup(name="g", description="", factors=(f,))]
        manifest = factor_library_manifest(groups)
        assert manifest["schema_version"] == STRUCTURED_FACTOR_LIBRARY_SCHEMA
        assert manifest["n_groups"] == 1
        assert manifest["n_factors"] == 1
        assert manifest["group_names"] == ["g"]
        assert isinstance(manifest["groups"], list)


# ── Resolve factor expressions ───────────────────────────────────────────────


class TestResolveFactorExpressions:
    def test_resolve(self) -> None:
        f1 = FactorSpec(id="a", expression="expr_a", family="f")
        f2 = FactorSpec(id="b", expression="expr_b", family="f")
        library = {
            "g": FactorGroup(name="g", description="", factors=(f1, f2)),
        }
        result = resolve_factor_expressions(["a", "b"], library)
        assert result == ["expr_a", "expr_b"]

    def test_unknown_id_raises(self) -> None:
        f = FactorSpec(id="a", expression="x", family="f")
        library = {"g": FactorGroup(name="g", description="", factors=(f,))}
        with pytest.raises(ValueError, match="Unknown factor id"):
            resolve_factor_expressions(["nonexistent"], library)


# ── Real YAML file loading ───────────────────────────────────────────────────


class TestRealFactorLibraryYAMLs:
    def test_cn_ohlcv_loads(self) -> None:
        path = Path("configs/factor_libraries/cn_ohlcv.yaml")
        if not path.exists():
            pytest.skip("cn_ohlcv.yaml not found")
        library = load_factor_library(path)
        # 4 feature groups + 1 factor_baselines group
        assert len(library) == 5
        assert "cn_short_reversal_liquidity" in library
        assert "cn_volatility_reversal" in library
        assert "cn_price_volume_pressure" in library
        assert "cn_balanced_ohlcv" in library
        assert "factor_baselines" in library
        # All factor ids globally unique
        all_ids = [f.id for g in library.values() for f in g.factors]
        assert len(all_ids) == len(set(all_ids))

    def test_cn_yaml_expressions_match_91(self) -> None:
        """Verify YAML factor expressions match the #91 cn_ranker_feature_groups."""
        path = Path("configs/factor_libraries/cn_ohlcv.yaml")
        if not path.exists():
            pytest.skip("cn_ohlcv.yaml not found")
        library = load_factor_library(path)

        # Build YAML group name -> frozenset of expressions
        yaml_exprs: dict[str, frozenset[str]] = {}
        for g in library.values():
            if g.name == "factor_baselines":
                continue
            yaml_exprs[g.name] = frozenset(f.expression for f in g.factors)

        # Compare to #91 legacy groups
        for legacy in cn_ranker_feature_groups():
            assert legacy.name in yaml_exprs, (
                f"Group '{legacy.name}' from #91 missing in YAML"
            )
            assert yaml_exprs[legacy.name] == frozenset(legacy.expressions), (
                f"Expression mismatch for group '{legacy.name}' vs #91"
            )

    def test_cn_baseline_expressions_match_91(self) -> None:
        """Verify YAML baseline factor expressions match #91 baselines."""
        path = Path("configs/factor_libraries/cn_ohlcv.yaml")
        if not path.exists():
            pytest.skip("cn_ohlcv.yaml not found")
        library = load_factor_library(path)
        # Baseline factors are in the factor_baselines group
        assert "factor_baselines" in library
        yaml_baselines: dict[str, str] = {}
        for f in library["factor_baselines"].factors:
            yaml_baselines[f.id] = f.expression

        # #91 baselines use different keys — compare expressions only
        legacy = cn_factor_baseline_expressions()
        yaml_exprs = set(yaml_baselines.values())
        legacy_exprs = set(legacy.values())
        assert yaml_exprs == legacy_exprs, (
            f"Baseline expression mismatch vs #91\n"
            f"  YAML:   {sorted(yaml_exprs)}\n"
            f"  #91:    {sorted(legacy_exprs)}"
        )

    def test_us_ohlcv_loads(self) -> None:
        path = Path("configs/factor_libraries/us_ohlcv.yaml")
        if not path.exists():
            pytest.skip("us_ohlcv.yaml not found")
        library = load_factor_library(path)
        # 4 feature groups + 1 factor_baselines group
        assert len(library) == 5
        assert "momentum" in library
        assert "momentum_volatility" in library
        assert "momentum_volatility_volume" in library
        assert "risk_controlled_momentum" in library
        assert "factor_baselines" in library
        all_ids = [f.id for g in library.values() for f in g.factors]
        assert len(all_ids) == len(set(all_ids))
