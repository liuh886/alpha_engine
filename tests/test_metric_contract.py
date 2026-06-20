"""Tests for the versioned metric contract (T46.6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.models.metric_contract import (
    MetricContract,
    normalize_metrics,
    validate_metrics,
)

# =========================================================================
# MetricContract — construction & introspection
# =========================================================================


class TestMetricContractConstruction:
    def test_v1_default(self):
        mc = MetricContract()
        assert mc.version == "v1"
        assert len(mc.fields) > 0

    def test_v1_explicit(self):
        mc = MetricContract(version="v1")
        assert mc.version == "v1"

    def test_unknown_version_raises(self):
        with pytest.raises(ValueError, match="Unknown metric contract version"):
            MetricContract(version="v99")

    def test_required_fields_subset_of_all(self):
        mc = MetricContract()
        assert set(mc.required_fields).issubset(set(mc.all_fields))

    def test_required_fields_are_annualized_return_and_max_drawdown(self):
        mc = MetricContract()
        assert "annualized_return" in mc.required_fields
        assert "max_drawdown" in mc.required_fields

    def test_optional_fields_include_sharpe(self):
        mc = MetricContract()
        assert "sharpe" in mc.optional_fields
        assert "information_ratio" in mc.optional_fields

    def test_field_spec_lookup(self):
        mc = MetricContract()
        spec = mc.field_spec("sharpe")
        assert spec is not None
        assert spec.name == "sharpe"
        assert spec.required is False

    def test_field_spec_lookup_missing(self):
        mc = MetricContract()
        assert mc.field_spec("nonexistent") is None

    def test_to_dict_roundtrip(self):
        mc = MetricContract()
        d = mc.to_dict()
        assert d["version"] == "v1"
        assert isinstance(d["fields"], list)
        names = [f["name"] for f in d["fields"]]
        assert "annualized_return" in names
        assert "sharpe" in names


# =========================================================================
# normalize_metrics
# =========================================================================


class TestNormalizeMetrics:
    """Normalisation handles missing fields, aliases, and coercion."""

    def test_empty_dict_yields_all_none(self):
        result = normalize_metrics({})
        mc = MetricContract()
        for name in mc.all_fields:
            assert result[name] is None, f"Expected None for {name}"

    def test_none_input_yields_all_none(self):
        result = normalize_metrics(None)  # type: ignore[arg-type]
        mc = MetricContract()
        assert all(result[k] is None for k in mc.all_fields)

    def test_canonical_key_passthrough(self):
        result = normalize_metrics({"annualized_return": 0.15, "max_drawdown": -0.20})
        assert result["annualized_return"] == pytest.approx(0.15)
        assert result["max_drawdown"] == pytest.approx(-0.20)

    def test_qlib_style_aliases(self):
        raw = {
            "Annualized Return": 0.12,
            "Information Ratio": 1.5,
            "Max Drawdown": -0.18,
            "Sharpe Ratio": 1.2,
            "Excess Return": 0.05,
        }
        result = normalize_metrics(raw)
        assert result["annualized_return"] == pytest.approx(0.12)
        assert result["information_ratio"] == pytest.approx(1.5)
        assert result["max_drawdown"] == pytest.approx(-0.18)
        assert result["sharpe"] == pytest.approx(1.2)
        assert result["excess_return"] == pytest.approx(0.05)

    def test_underscore_style_aliases(self):
        raw = {
            "sharpe_ratio": 1.1,
            "ic_ir": 0.8,
            "spearman_ic": 0.05,
            "annual_return": 0.10,
            "max_dd": -0.15,
        }
        result = normalize_metrics(raw)
        assert result["sharpe"] == pytest.approx(1.1)
        assert result["icir"] == pytest.approx(0.8)
        assert result["rank_ic"] == pytest.approx(0.05)
        assert result["annualized_return"] == pytest.approx(0.10)
        assert result["max_drawdown"] == pytest.approx(-0.15)

    def test_mixed_alias_and_canonical(self):
        raw = {
            "Sharpe Ratio": 1.3,
            "annualized_return": 0.20,
            "ic": 0.06,
            "coverage": 0.95,
        }
        result = normalize_metrics(raw)
        assert result["sharpe"] == pytest.approx(1.3)
        assert result["annualized_return"] == pytest.approx(0.20)
        assert result["ic"] == pytest.approx(0.06)
        assert result["coverage"] == pytest.approx(0.95)

    def test_string_value_coerced_to_float(self):
        result = normalize_metrics({"annualized_return": "0.15", "max_drawdown": "-0.20"})
        assert result["annualized_return"] == pytest.approx(0.15)
        assert result["max_drawdown"] == pytest.approx(-0.20)

    def test_uncoercible_value_becomes_none(self):
        result = normalize_metrics({"annualized_return": "not_a_number"})
        assert result["annualized_return"] is None

    def test_unknown_keys_dropped(self):
        result = normalize_metrics({"annualized_return": 0.10, "some_random_key": 42})
        assert "some_random_key" not in result
        assert result["annualized_return"] == pytest.approx(0.10)

    def test_win_rate_mapped_to_none(self):
        """'Win Rate' is explicitly mapped to None in the alias table."""
        result = normalize_metrics({"Win Rate": 0.6, "annualized_return": 0.10, "max_drawdown": -0.10})
        assert "Win Rate" not in result
        assert "win_rate" not in result
        assert result["annualized_return"] == pytest.approx(0.10)

    def test_integer_value_coerced(self):
        result = normalize_metrics({"sample_count": 100})
        assert result["sample_count"] == pytest.approx(100.0)

    def test_result_has_all_contract_fields(self):
        mc = MetricContract()
        result = normalize_metrics({"annualized_return": 0.10, "max_drawdown": -0.05})
        assert set(result.keys()) == set(mc.all_fields)

    def test_field_order_matches_contract(self):
        mc = MetricContract()
        result = normalize_metrics({})
        assert list(result.keys()) == mc.all_fields


# =========================================================================
# validate_metrics
# =========================================================================


class TestValidateMetrics:
    """Validation rejects missing required fields."""

    def test_all_required_present(self):
        metrics = normalize_metrics({
            "annualized_return": 0.15,
            "max_drawdown": -0.20,
        })
        vr = validate_metrics(metrics)
        assert vr.ok is True
        assert vr.missing_required == []
        assert vr.version == "v1"
        assert bool(vr) is True

    def test_missing_annualized_return(self):
        metrics = normalize_metrics({"max_drawdown": -0.20})
        vr = validate_metrics(metrics)
        assert vr.ok is False
        assert "annualized_return" in vr.missing_required

    def test_missing_max_drawdown(self):
        metrics = normalize_metrics({"annualized_return": 0.15})
        vr = validate_metrics(metrics)
        assert vr.ok is False
        assert "max_drawdown" in vr.missing_required

    def test_missing_both_required(self):
        metrics = normalize_metrics({})
        vr = validate_metrics(metrics)
        assert vr.ok is False
        assert "annualized_return" in vr.missing_required
        assert "max_drawdown" in vr.missing_required

    def test_optional_fields_not_required(self):
        metrics = normalize_metrics({
            "annualized_return": 0.15,
            "max_drawdown": -0.20,
        })
        vr = validate_metrics(metrics)
        assert vr.ok is True
        # Sharpe is optional — None is fine
        assert metrics.get("sharpe") is None

    def test_validate_raw_dict_fails_if_required_missing(self):
        """validate_metrics works on raw dicts too (not just normalised)."""
        vr = validate_metrics({"sharpe": 1.0})
        assert vr.ok is False

    def test_version_compatibility_v1(self):
        metrics = normalize_metrics({
            "annualized_return": 0.10,
            "max_drawdown": -0.05,
        }, version="v1")
        vr = validate_metrics(metrics, version="v1")
        assert vr.ok is True

    def test_unknown_version_raises(self):
        with pytest.raises(ValueError, match="Unknown metric contract version"):
            validate_metrics({}, version="v99")


# =========================================================================
# Normalise + validate integration
# =========================================================================


class TestNormalizeAndValidate:
    """End-to-end: normalise raw dict then validate."""

    def test_full_qlib_metrics(self):
        raw = {
            "Annualized Return": 0.18,
            "Information Ratio": 1.2,
            "Max Drawdown": -0.22,
            "Sharpe Ratio": 1.4,
        }
        norm = normalize_metrics(raw)
        vr = validate_metrics(norm)
        assert vr.ok is True
        assert norm["annualized_return"] == pytest.approx(0.18)
        assert norm["sharpe"] == pytest.approx(1.4)

    def test_walk_forward_metrics(self):
        raw = {
            "ic": 0.06,
            "rank_ic": 0.055,
            "icir": 0.8,
            "consistency_score": 0.72,
            "annual_return": 0.12,
            "sharpe": 0.9,
            "max_dd": -0.15,
        }
        norm = normalize_metrics(raw)
        vr = validate_metrics(norm)
        assert vr.ok is True
        assert norm["consistency"] == pytest.approx(0.72)
        assert norm["annualized_return"] == pytest.approx(0.12)

    def test_factor_evaluator_metrics(self):
        raw = {
            "IC": 0.08,
            "ICIR": 1.1,
            "coverage": 0.92,
            "positive_ratio": 0.68,
        }
        norm = normalize_metrics(raw)
        # Required fields are missing — should fail validation
        vr = validate_metrics(norm)
        assert vr.ok is False
        assert "annualized_return" in vr.missing_required
        assert "max_drawdown" in vr.missing_required

    def test_missing_values_are_none_not_zero(self):
        """Core contract guarantee: missing metrics are None, not 0."""
        raw = {"annualized_return": 0.10, "max_drawdown": -0.05}
        norm = normalize_metrics(raw)
        assert norm["sharpe"] is None
        assert norm["information_ratio"] is None
        assert norm["volatility"] is None
        assert norm["ic"] is None
        # None != 0 — this is the key invariant
        assert norm["sharpe"] != 0

    def test_zero_is_a_valid_value(self):
        """Explicit 0 should remain 0, not be confused with missing."""
        raw = {"annualized_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
        norm = normalize_metrics(raw)
        assert norm["annualized_return"] == pytest.approx(0.0)
        assert norm["max_drawdown"] == pytest.approx(0.0)
        assert norm["sharpe"] == pytest.approx(0.0)
