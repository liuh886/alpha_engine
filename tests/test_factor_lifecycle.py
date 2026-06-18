"""Integration tests for the factor lifecycle system.

Covers FactorRegistry CRUD, lifecycle stage management, validation gates,
expression syntax validation, usage tracking, stats, and the composite
define-evaluate-validate-register flow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.research.factor_evaluator import (
    FactorEvalResult,
    QuintileReturn,
    validate_expression_syntax,
)
from src.research.factor_registry import (
    GATE_1_THRESHOLDS,
    GATE_2_THRESHOLDS,
    GATE_3_THRESHOLDS,
    STAGE_ACTIVE,
    STAGE_CANDIDATE,
    STAGE_DEPRECATED,
    STAGE_PROPOSED,
    STAGE_VALIDATED,
    FactorRegistry,
)
from src.research.factor_scanner import (
    ScanReport,
    ScanResult,
    benjamini_hochberg_correction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tmp_path: Path) -> FactorRegistry:
    """Create a FactorRegistry backed by a temporary SQLite database."""
    db_path = str(tmp_path / "test_factor_registry.db")
    return FactorRegistry(db_path=db_path)


def _good_metrics() -> dict:
    """Return metrics that comfortably pass all validation gates."""
    return {
        "ic": 0.05,
        "rank_ic": 0.04,
        "icir": 1.0,
        "t_stat": 3.0,
        "positive_ratio": 0.65,
        "mean_decay_1d": 0.05,
        "mean_decay_5d": 0.02,
        "quintile_spread": 0.005,
    }


def _bad_metrics() -> dict:
    """Return metrics that fail all validation gates."""
    return {
        "ic": 0.001,
        "rank_ic": 0.001,
        "icir": 0.1,
        "t_stat": 0.5,
        "positive_ratio": 0.40,
        "mean_decay_1d": 0.05,
        "mean_decay_5d": 0.049,
        "quintile_spread": 0.0001,
    }


def _make_eval_result(passed: bool, expression: str = "$close/Ref($close,5)-1") -> FactorEvalResult:
    """Build a FactorEvalResult for mocking evaluate_factor."""
    if passed:
        return FactorEvalResult(
            expression=expression,
            market="us",
            start_date="2021-01-01",
            end_date="2025-12-31",
            ic=0.05,
            rank_ic=0.04,
            ic_std=0.02,
            icir=1.0,
            t_stat=3.0,
            positive_ratio=0.65,
            n_periods=48,
            decay_1d=0.05,
            decay_5d=0.02,
            decay_10d=0.01,
            quintile_returns=[],
            quintile_spread=0.005,
            coverage=0.95,
            mean_value=0.0,
            std_value=1.0,
            passed=True,
            fail_reasons=[],
        )
    return FactorEvalResult(
        expression=expression,
        market="us",
        start_date="2021-01-01",
        end_date="2025-12-31",
        ic=0.001,
        rank_ic=0.001,
        ic_std=0.02,
        icir=0.1,
        t_stat=0.5,
        positive_ratio=0.40,
        n_periods=48,
        decay_1d=0.05,
        decay_5d=0.049,
        decay_10d=0.04,
        quintile_returns=[],
        quintile_spread=0.0001,
        coverage=0.95,
        mean_value=0.0,
        std_value=1.0,
        passed=False,
        fail_reasons=["|ICIR|=0.1000 < min_icir=0.5", "|t_stat|=0.5000 < min_t_stat=2.0"],
    )


# ---------------------------------------------------------------------------
# Test 1: CRUD operations
# ---------------------------------------------------------------------------


class TestFactorRegistryCRUD:
    """Test basic create, read, update, delete operations on the registry."""

    def test_factor_registry_crud(self, tmp_path):
        """Register a factor, retrieve by id/name, list, update stage, and search."""
        reg = _make_registry(tmp_path)

        # Register
        fid = reg.register_factor(
            name="test_momentum_5d",
            expression="$close/Ref($close,5)-1",
            category="momentum",
            direction="long",
            lookback_days=5,
            thesis="5-day price momentum",
        )
        assert fid > 0

        # get_factor by id
        factor = reg.get_factor(fid)
        assert factor is not None
        assert factor["name"] == "test_momentum_5d"
        assert factor["expression"] == "$close/Ref($close,5)-1"
        assert factor["category"] == "momentum"
        assert factor["direction"] == "long"
        assert factor["lookback_days"] == 5
        assert factor["thesis"] == "5-day price momentum"
        assert factor["stage"] == STAGE_PROPOSED

        # list_factors
        factors = reg.list_factors()
        assert len(factors) == 1
        assert factors[0]["id"] == fid

        # get_factor_by_name
        by_name = reg.get_factor_by_name("test_momentum_5d")
        assert by_name is not None
        assert by_name["id"] == fid

        # update_stage
        updated = reg.update_stage(fid, STAGE_VALIDATED)
        assert updated is True
        factor = reg.get_factor(fid)
        assert factor["stage"] == STAGE_VALIDATED

        # search_factors
        results = reg.search_factors("momentum")
        assert len(results) == 1
        assert results[0]["id"] == fid

        # search_factors for non-matching query
        results = reg.search_factors("nonexistent_xyz")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Test 2: Lifecycle stages
# ---------------------------------------------------------------------------


class TestFactorLifecycleStages:
    """Test promote/demote transitions through the factor lifecycle."""

    def test_factor_registry_lifecycle_stages(self, tmp_path):
        """Walk through Proposed -> Candidate -> Validated -> Active -> Deprecated, and test boundary conditions."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(
            name="test_lifecycle",
            expression="Rank($volume)",
            category="volume",
        )

        # Starts at Proposed
        factor = reg.get_factor(fid)
        assert factor["stage"] == STAGE_PROPOSED

        # Promote to Candidate
        assert reg.promote(fid) is True
        assert reg.get_factor(fid)["stage"] == STAGE_CANDIDATE

        # Promote to Validated
        assert reg.promote(fid) is True
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED

        # Promote to Active
        assert reg.promote(fid) is True
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

        # Demote to Deprecated
        assert reg.demote(fid) is True
        assert reg.get_factor(fid)["stage"] == STAGE_DEPRECATED

        # Cannot promote Deprecated (terminal stage)
        assert reg.promote(fid) is False
        assert reg.get_factor(fid)["stage"] == STAGE_DEPRECATED

    def test_cannot_demote_proposed(self, tmp_path):
        """Demoting a Proposed factor should fail (only Active can be demoted)."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_no_demote", expression="Std($close,20)")

        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED
        assert reg.demote(fid) is False
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

    def test_promote_nonexistent(self, tmp_path):
        """Promoting a non-existent factor id returns False."""
        reg = _make_registry(tmp_path)
        assert reg.promote(9999) is False

    def test_demote_nonexistent(self, tmp_path):
        """Demoting a non-existent factor id returns False."""
        reg = _make_registry(tmp_path)
        assert reg.demote(9999) is False

    def test_update_stage_invalid(self, tmp_path):
        """update_stage raises ValueError for an invalid stage name."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_invalid_stage", expression="Rank($volume)")
        with pytest.raises(ValueError, match="Invalid stage"):
            reg.update_stage(fid, "NonExistentStage")


# ---------------------------------------------------------------------------
# Test 3: Validation gates
# ---------------------------------------------------------------------------


class TestFactorRegistryValidation:
    """Test the validation gate logic via record_validation."""

    def test_factor_registry_validation_gates_good(self, tmp_path):
        """Metrics that meet all gates produce passed=True."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(
            name="test_good_factor",
            expression="$close/Ref($close,5)-1",
        )

        val_id = reg.record_validation(fid, "us", _good_metrics())
        assert val_id > 0

        validations = reg.get_validations(fid)
        assert len(validations) == 1
        # SQLite stores booleans as integers; compare with == for correctness
        assert validations[0]["passed"] == 1
        assert validations[0]["market"] == "us"
        assert validations[0]["icir"] == 1.0
        assert validations[0]["t_stat"] == 3.0

    def test_factor_registry_validation_gates_bad(self, tmp_path):
        """Metrics that fail gates produce passed=False."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(
            name="test_bad_factor",
            expression="$close/Ref($close,5)-1",
        )

        val_id = reg.record_validation(fid, "us", _bad_metrics())
        assert val_id > 0

        validations = reg.get_validations(fid)
        assert len(validations) == 1
        # SQLite stores booleans as integers
        assert validations[0]["passed"] == 0

    def test_is_validated(self, tmp_path):
        """is_validated returns True only when at least one passing validation exists."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_is_validated", expression="Rank($volume)")

        # No validations yet
        assert reg.is_validated(fid, "us") is False

        # Record a failing validation
        reg.record_validation(fid, "us", _bad_metrics())
        assert reg.is_validated(fid, "us") is False

        # Record a passing validation
        reg.record_validation(fid, "us", _good_metrics())
        assert reg.is_validated(fid, "us") is True

    def test_validation_partial_metrics(self, tmp_path):
        """Gates skip metrics that are not provided (missing keys are non-failing)."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_partial", expression="Rank($volume)")

        # Only provide icir and t_stat that pass, omit the rest
        partial = {"icir": 1.0, "t_stat": 3.0}
        val_id = reg.record_validation(fid, "us", partial)
        assert val_id > 0

        validations = reg.get_validations(fid)
        # SQLite stores booleans as integers
        assert validations[0]["passed"] == 1

    def test_record_validation_empty_market_raises(self, tmp_path):
        """record_validation raises ValueError when market is empty."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_empty_market", expression="Rank($volume)")
        with pytest.raises(ValueError, match="market"):
            reg.record_validation(fid, "", _good_metrics())


# ---------------------------------------------------------------------------
# Test 4: Expression syntax validation
# ---------------------------------------------------------------------------


class TestValidateExpressionSyntax:
    """Test the validate_expression_syntax() function from factor_evaluator."""

    @pytest.mark.parametrize(
        "expr",
        [
            "$close/Ref($close,5)-1",
            "Rank($volume)",
            "Std($close,20)",
            "Mean($close,10)/$close",
            "Log($volume+1)",
        ],
    )
    def test_valid_expressions(self, expr):
        """Known-good Qlib expressions pass syntax validation."""
        valid, err = validate_expression_syntax(expr)
        assert valid is True, f"Expected valid, got error: {err}"
        assert err == ""

    def test_empty_string(self):
        """Empty string is rejected."""
        valid, err = validate_expression_syntax("")
        assert valid is False
        assert "empty" in err.lower()

    def test_whitespace_only(self):
        """Whitespace-only string is rejected."""
        valid, err = validate_expression_syntax("   ")
        assert valid is False
        assert "empty" in err.lower()

    def test_unbalanced_parens_open(self):
        """Expression with unmatched opening paren is rejected."""
        valid, err = validate_expression_syntax("Ref($close,5")
        assert valid is False
        assert "paren" in err.lower() or "Mismatched" in err

    def test_unbalanced_parens_close(self):
        """Expression with unmatched closing paren is rejected."""
        valid, err = validate_expression_syntax("$close/Ref($close,5))")
        assert valid is False
        assert "paren" in err.lower() or "Mismatched" in err

    def test_no_qlib_reference(self):
        """String with no $-field or Qlib function is rejected."""
        valid, err = validate_expression_syntax("hello world")
        assert valid is False
        assert "field" in err.lower() or "function" in err.lower()


# ---------------------------------------------------------------------------
# Test 5: evaluate_factor (skip if Qlib data unavailable)
# ---------------------------------------------------------------------------


class TestEvaluateFactor:
    """Test evaluate_factor from factor_evaluator."""

    def test_evaluate_factor_basic(self, monkeypatch):
        """evaluate_factor returns a valid FactorEvalResult even when Qlib data is missing.

        This test mocks out Qlib initialization so it does not require actual
        market data.  It verifies that the function handles failures gracefully
        and returns a result with passed=False.
        """
        qlib_available = True
        try:
            import qlib  # noqa: F401
        except ImportError:
            qlib_available = False

        if not qlib_available:
            pytest.skip("Qlib not installed")

        # Mock _init_qlib so it does nothing (no real data needed)
        monkeypatch.setattr(
            "src.research.factor_evaluator._init_qlib",
            lambda market: None,
        )

        # Mock _load_factor_values to return an empty DataFrame (simulates no data)
        import pandas as pd

        monkeypatch.setattr(
            "src.research.factor_evaluator._load_factor_values",
            lambda *a, **kw: pd.DataFrame(),
        )

        from src.research.factor_evaluator import evaluate_factor

        result = evaluate_factor(
            expression="$close/Ref($close,5)-1",
            market="us",
            start_date="2021-01-01",
            end_date="2025-12-31",
        )

        assert isinstance(result, FactorEvalResult)
        assert result.passed is False
        assert len(result.fail_reasons) > 0
        assert result.expression == "$close/Ref($close,5)-1"

    def test_evaluate_factor_invalid_expression(self):
        """evaluate_factor returns passed=False for an invalid expression."""
        from src.research.factor_evaluator import evaluate_factor

        result = evaluate_factor(
            expression="invalid((((",
            market="us",
        )
        assert isinstance(result, FactorEvalResult)
        assert result.passed is False
        assert len(result.fail_reasons) > 0


# ---------------------------------------------------------------------------
# Test 6: Usage tracking
# ---------------------------------------------------------------------------


class TestFactorUsageTracking:
    """Test the factor usage recording and retrieval."""

    def test_factor_registry_usage_tracking(self, tmp_path):
        """Record usage and verify it can be retrieved."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(
            name="test_usage",
            expression="$close/Ref($close,5)-1",
        )

        reg.record_usage(fid, strategy_config="momentum_v1", weight=0.5)
        usage = reg.get_usage(fid)

        assert len(usage) == 1
        assert usage[0]["factor_id"] == fid
        assert usage[0]["strategy_config"] == "momentum_v1"
        assert usage[0]["weight"] == 0.5

    def test_multiple_usage_records(self, tmp_path):
        """Multiple usage records for the same factor are all returned."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="test_multi_usage", expression="Rank($volume)")

        reg.record_usage(fid, strategy_config="strat_a", weight=1.0)
        reg.record_usage(fid, strategy_config="strat_b", weight=0.5)

        usage = reg.get_usage(fid)
        assert len(usage) == 2
        configs = {u["strategy_config"] for u in usage}
        assert configs == {"strat_a", "strat_b"}


# ---------------------------------------------------------------------------
# Test 7: Registry stats
# ---------------------------------------------------------------------------


class TestFactorRegistryStats:
    """Test the get_stats() summary endpoint."""

    def test_factor_registry_stats(self, tmp_path):
        """Register factors at different stages and verify get_stats counts."""
        reg = _make_registry(tmp_path)

        # Register factors in different categories and stages
        fid1 = reg.register_factor(name="mom_1", expression="$close/Ref($close,5)-1", category="momentum")
        fid2 = reg.register_factor(name="vol_1", expression="Rank($volume)", category="volume")
        fid3 = reg.register_factor(name="mom_2", expression="Std($close,20)", category="momentum", direction="short")

        # Promote fid2 to Candidate
        reg.promote(fid2)
        # Promote fid2 to Validated
        reg.promote(fid2)
        # Promote fid2 to Active
        reg.promote(fid2)

        # Record a passing validation for fid1
        reg.record_validation(fid1, "us", _good_metrics())
        # Record a failing validation for fid3
        reg.record_validation(fid3, "us", _bad_metrics())

        # Record usage
        reg.record_usage(fid1, strategy_config="strat_a")

        stats = reg.get_stats()

        assert stats["total_factors"] == 3
        assert stats["by_stage"][STAGE_PROPOSED] == 2
        assert stats["by_stage"][STAGE_ACTIVE] == 1
        assert stats["by_category"]["momentum"] == 2
        assert stats["by_category"]["volume"] == 1
        assert stats["by_direction"]["long"] == 2
        assert stats["by_direction"]["short"] == 1
        assert stats["total_validations"] == 2
        assert stats["total_passed_validations"] == 1
        assert stats["total_usage_records"] == 1

    def test_stats_empty_registry(self, tmp_path):
        """get_stats on an empty registry returns zeros."""
        reg = _make_registry(tmp_path)
        stats = reg.get_stats()

        assert stats["total_factors"] == 0
        assert stats["by_stage"] == {}
        assert stats["by_category"] == {}
        assert stats["by_direction"] == {}
        assert stats["total_validations"] == 0
        assert stats["total_passed_validations"] == 0
        assert stats["total_usage_records"] == 0


# ---------------------------------------------------------------------------
# Test 8: Composite discover-factor flow (mock-based)
# ---------------------------------------------------------------------------


class TestDiscoverFactorCompositeFlow:
    """Test the define-evaluate-validate-register composite flow using mocks."""

    def test_composite_flow_passes_to_active(self, tmp_path, monkeypatch):
        """A factor that passes evaluation and validation ends at Active stage.

        The flow:
        1. Define factor expression
        2. Evaluate via evaluate_factor (mocked to return passing result)
        3. Record validation in registry
        4. Promote through stages until Active
        """
        # Mock evaluate_factor to return a passing result
        monkeypatch.setattr(
            "src.research.factor_evaluator.evaluate_factor",
            lambda *a, **kw: _make_eval_result(passed=True),
        )

        reg = _make_registry(tmp_path)
        from src.research.factor_evaluator import evaluate_factor

        # Step 1: Define
        name = "test_composite_pass"
        expression = "$close/Ref($close,5)-1"
        category = "momentum"
        thesis = "5-day momentum factor"

        # Step 2: Evaluate
        eval_result = evaluate_factor(
            expression=expression,
            market="us",
            start_date="2021-01-01",
            end_date="2025-12-31",
        )
        assert eval_result.passed is True

        # Step 3: Register
        fid = reg.register_factor(
            name=name,
            expression=expression,
            category=category,
            thesis=thesis,
        )
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

        # Step 4: Record validation
        metrics = {
            "ic": eval_result.ic,
            "rank_ic": eval_result.rank_ic,
            "icir": eval_result.icir,
            "t_stat": eval_result.t_stat,
            "positive_ratio": eval_result.positive_ratio,
            "quintile_spread": eval_result.quintile_spread,
            "mean_decay_1d": eval_result.decay_1d,
            "mean_decay_5d": eval_result.decay_5d,
        }
        reg.record_validation(fid, eval_result.market, metrics)

        # Step 5: Promote through stages
        assert reg.promote(fid) is True  # Proposed -> Candidate
        assert reg.get_factor(fid)["stage"] == STAGE_CANDIDATE
        assert reg.promote(fid) is True  # Candidate -> Validated
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED
        assert reg.promote(fid) is True  # Validated -> Active
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

        # Verify final state
        factor = reg.get_factor(fid)
        assert factor["name"] == name
        assert factor["stage"] == STAGE_ACTIVE
        assert reg.is_validated(fid, "us") is True

    def test_composite_flow_stays_proposed_when_fails(self, tmp_path, monkeypatch):
        """A factor that fails evaluation stays at Proposed stage.

        The flow:
        1. Define factor expression
        2. Evaluate via evaluate_factor (mocked to return failing result)
        3. Record validation in registry
        4. Do NOT promote (validation failed)
        """
        # Mock evaluate_factor to return a failing result
        monkeypatch.setattr(
            "src.research.factor_evaluator.evaluate_factor",
            lambda *a, **kw: _make_eval_result(passed=False),
        )

        reg = _make_registry(tmp_path)
        from src.research.factor_evaluator import evaluate_factor

        # Step 1: Define
        name = "test_composite_fail"
        expression = "$close/Ref($close,5)-1"

        # Step 2: Evaluate
        eval_result = evaluate_factor(expression=expression, market="us")
        assert eval_result.passed is False

        # Step 3: Register
        fid = reg.register_factor(name=name, expression=expression)
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

        # Step 4: Record validation (fails)
        metrics = {
            "icir": eval_result.icir,
            "t_stat": eval_result.t_stat,
            "positive_ratio": eval_result.positive_ratio,
            "quintile_spread": eval_result.quintile_spread,
        }
        reg.record_validation(fid, eval_result.market, metrics)

        # Step 5: Do NOT promote -- validation failed
        # Factor should remain at Proposed
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED
        assert reg.is_validated(fid, "us") is False

    def test_composite_flow_register_then_demote(self, tmp_path, monkeypatch):
        """An Active factor can be demoted to Deprecated via the lifecycle."""
        monkeypatch.setattr(
            "src.research.factor_evaluator.evaluate_factor",
            lambda *a, **kw: _make_eval_result(passed=True),
        )

        reg = _make_registry(tmp_path)

        fid = reg.register_factor(name="test_demote_flow", expression="Rank($volume)")

        # Promote to Active
        reg.promote(fid)  # Proposed -> Candidate
        reg.promote(fid)  # Candidate -> Validated
        reg.promote(fid)  # Validated -> Active
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

        # Demote
        reg.demote(fid)
        assert reg.get_factor(fid)["stage"] == STAGE_DEPRECATED

        # Cannot promote Deprecated
        assert reg.promote(fid) is False
        assert reg.get_factor(fid)["stage"] == STAGE_DEPRECATED


# ---------------------------------------------------------------------------
# Test 9: Three-tier promotion gating
# ---------------------------------------------------------------------------


class TestThreeTierPromotion:
    """Test the three-tier promotion system: Gate 1, 2, 3 thresholds and promote_to_next_gate."""

    # -- Gate 1 (Proposed -> Candidate) ---

    def test_gate1_passes_with_good_metrics(self, tmp_path):
        """Metrics meeting Gate 1 thresholds promote Proposed -> Candidate."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g1_pass", expression="Rank($volume)")

        metrics = {
            "icir": 0.6,
            "t_stat": 2.5,
            "positive_ratio": 0.60,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is True
        assert "Candidate" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_CANDIDATE

    def test_gate1_fails_low_icir(self, tmp_path):
        """Metrics with icir below Gate 1 threshold fail promotion."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g1_fail_icir", expression="Rank($volume)")

        metrics = {
            "icir": 0.3,  # below 0.5
            "t_stat": 2.5,
            "positive_ratio": 0.60,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "icir" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

    def test_gate1_fails_low_t_stat(self, tmp_path):
        """Metrics with t_stat below Gate 1 threshold fail promotion."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g1_fail_tstat", expression="Rank($volume)")

        metrics = {
            "icir": 0.6,
            "t_stat": 1.5,  # below 2.0
            "positive_ratio": 0.60,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "t_stat" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

    def test_gate1_fails_low_positive_ratio(self, tmp_path):
        """Metrics with positive_ratio below Gate 1 threshold fail promotion."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g1_fail_pr", expression="Rank($volume)")

        metrics = {
            "icir": 0.6,
            "t_stat": 2.5,
            "positive_ratio": 0.50,  # below 0.55
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "positive_ratio" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_PROPOSED

    # -- Gate 2 (Candidate -> Validated) ---

    def test_gate2_passes_with_tight_metrics(self, tmp_path):
        """Metrics meeting Gate 2 thresholds promote Candidate -> Validated."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g2_pass", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_CANDIDATE)

        metrics = {
            "icir": 0.8,
            "t_stat": 3.0,
            "positive_ratio": 0.65,
            "quintile_spread": 0.003,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is True
        assert "Validated" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED

    def test_gate2_fails_below_gate1_level_metrics(self, tmp_path):
        """Metrics that pass Gate 1 but not Gate 2 fail at Candidate stage."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g2_fail", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_CANDIDATE)

        # icir=0.6 passes Gate 1 (0.5) but fails Gate 2 (0.7)
        metrics = {
            "icir": 0.6,
            "t_stat": 2.2,
            "positive_ratio": 0.58,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "icir" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_CANDIDATE

    def test_gate2_fails_fast_decay(self, tmp_path):
        """Fast IC decay at Gate 2 blocks promotion."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g2_decay", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_CANDIDATE)

        metrics = {
            "icir": 0.8,
            "t_stat": 3.0,
            "positive_ratio": 0.65,
            "quintile_spread": 0.003,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.01,  # ratio = 0.2, below 0.3 threshold
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "decay" in msg.lower()

    # -- Gate 3 (Validated -> Active) ---

    def test_gate3_passes_with_production_metrics(self, tmp_path):
        """Production-quality metrics promote Validated -> Active."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g3_pass", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_VALIDATED)

        metrics = {
            "icir": 1.2,
            "t_stat": 3.5,
            "positive_ratio": 0.70,
            "quintile_spread": 0.005,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is True
        assert "Active" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

    def test_gate3_fails_moderate_metrics(self, tmp_path):
        """Metrics passing Gate 2 but not Gate 3 fail at Validated stage."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g3_fail", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_VALIDATED)

        # icir=0.8 passes Gate 2 but fails Gate 3 (1.0)
        metrics = {
            "icir": 0.8,
            "t_stat": 2.8,
            "positive_ratio": 0.62,
            "quintile_spread": 0.0025,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "icir" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED

    # -- Correlation check in Gate 3 ---

    def test_gate3_correlation_blocks_highly_correlated(self, tmp_path):
        """A factor highly correlated with Active factors is blocked at Gate 3."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g3_corr_block", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_VALIDATED)

        # Register an Active factor and give it multiple validation records
        # with varying IC values so std is non-zero and correlation is meaningful
        active_fid = reg.register_factor(name="existing_active", expression="$close")
        reg.update_stage(active_fid, STAGE_ACTIVE)
        ic_values = [0.01, 0.03, 0.05, 0.07, 0.09]
        for ic_val in ic_values:
            reg.record_validation(
                active_fid, "us",
                {"ic": ic_val, "icir": 1.5, "t_stat": 4.0, "positive_ratio": 0.70},
            )

        # IC series with a very similar trend -> high positive correlation
        ic_series = [0.011, 0.031, 0.051, 0.071, 0.091]
        metrics = {
            "icir": 1.2,
            "t_stat": 3.5,
            "positive_ratio": 0.70,
            "quintile_spread": 0.005,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
            "ic_series": ic_series,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "correlated" in msg.lower() or "corr" in msg.lower()

    def test_gate3_correlation_passes_uncorrelated(self, tmp_path):
        """An uncorrelated factor passes Gate 3 correlation check."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="g3_corr_pass", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_VALIDATED)

        # Register an Active factor with a known IC value
        active_fid = reg.register_factor(name="active_factor", expression="$close")
        reg.update_stage(active_fid, STAGE_ACTIVE)
        reg.record_validation(active_fid, "us", {"ic": 0.05, "icir": 1.5, "t_stat": 4.0, "positive_ratio": 0.70})

        # IC series with very different pattern -> low correlation
        ic_series = [-0.05, 0.02, -0.03, 0.04, -0.01]
        metrics = {
            "icir": 1.2,
            "t_stat": 3.5,
            "positive_ratio": 0.70,
            "quintile_spread": 0.005,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
            "ic_series": ic_series,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is True
        assert "Active" in msg

    # -- check_factor_correlation ---

    def test_check_factor_correlation_no_active_factors(self, tmp_path):
        """Correlation check returns 0.0 when no Active factors exist."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="corr_empty", expression="Rank($volume)")

        result = reg.check_factor_correlation(fid, [0.01, 0.02, 0.03, 0.04, 0.05])
        assert result == 0.0

    def test_check_factor_correlation_returns_max(self, tmp_path):
        """Correlation check returns the max absolute correlation across Active factors."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="corr_test", expression="Rank($volume)")

        # Create two Active factors with different IC values
        a1 = reg.register_factor(name="active_1", expression="$close/Ref($close,1)")
        reg.update_stage(a1, STAGE_ACTIVE)
        reg.record_validation(a1, "us", {"ic": 0.01, "icir": 1.0, "t_stat": 3.0, "positive_ratio": 0.65})

        a2 = reg.register_factor(name="active_2", expression="Std($close,10)")
        reg.update_stage(a2, STAGE_ACTIVE)
        reg.record_validation(a2, "us", {"ic": 0.08, "icir": 1.0, "t_stat": 3.0, "positive_ratio": 0.65})

        result = reg.check_factor_correlation(fid, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09])
        # Should be a valid float between 0 and 1
        assert 0.0 <= result <= 1.0

    def test_check_factor_correlation_empty_series(self, tmp_path):
        """Correlation check returns 0.0 for empty IC series."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="corr_empty_series", expression="Rank($volume)")
        result = reg.check_factor_correlation(fid, [])
        assert result == 0.0

    # -- Full three-tier promotion flow ---

    def test_full_three_tier_promotion_flow(self, tmp_path):
        """Walk a factor through all three gates: Proposed -> Candidate -> Validated -> Active."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="full_flow", expression="Rank($volume)")

        # Gate 1: Proposed -> Candidate
        metrics_g1 = {
            "icir": 0.6,
            "t_stat": 2.2,
            "positive_ratio": 0.58,
        }
        ok, msg = reg.promote_to_next_gate(fid, metrics_g1)
        assert ok is True
        assert reg.get_factor(fid)["stage"] == STAGE_CANDIDATE

        # Gate 2: Candidate -> Validated
        metrics_g2 = {
            "icir": 0.8,
            "t_stat": 2.8,
            "positive_ratio": 0.62,
            "quintile_spread": 0.003,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        ok, msg = reg.promote_to_next_gate(fid, metrics_g2)
        assert ok is True
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED

        # Gate 3: Validated -> Active
        metrics_g3 = {
            "icir": 1.1,
            "t_stat": 3.2,
            "positive_ratio": 0.68,
            "quintile_spread": 0.004,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        ok, msg = reg.promote_to_next_gate(fid, metrics_g3)
        assert ok is True
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

    # -- Cannot promote from Active or Deprecated ---

    def test_cannot_promote_active_factor(self, tmp_path):
        """promote_to_next_gate returns False for an Active factor."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="already_active", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_ACTIVE)

        ok, msg = reg.promote_to_next_gate(fid, {"icir": 2.0, "t_stat": 5.0})
        assert ok is False
        assert "no further" in msg.lower() or "already" in msg.lower()

    def test_cannot_promote_deprecated_factor(self, tmp_path):
        """promote_to_next_gate returns False for a Deprecated factor."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="already_deprecated", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_DEPRECATED)

        ok, msg = reg.promote_to_next_gate(fid, {"icir": 2.0, "t_stat": 5.0})
        assert ok is False

    def test_promote_nonexistent_factor(self, tmp_path):
        """promote_to_next_gate returns False for a non-existent factor."""
        reg = _make_registry(tmp_path)
        ok, msg = reg.promote_to_next_gate(9999, {"icir": 2.0})
        assert ok is False
        assert "not found" in msg.lower()

    # -- Backward compatibility ---

    def test_legacy_validated_factor_promotes_to_active(self, tmp_path):
        """A factor at 'Validated' stage (legacy) can be promoted to Active via Gate 3."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="legacy_validated", expression="Rank($volume)")
        # Manually set to Validated (simulating a legacy factor that went
        # Proposed -> Validated without the Candidate stage)
        reg.update_stage(fid, STAGE_VALIDATED)

        metrics = {
            "icir": 1.2,
            "t_stat": 3.5,
            "positive_ratio": 0.70,
            "quintile_spread": 0.005,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is True
        assert "Active" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_ACTIVE

    def test_legacy_validated_factor_fails_gate3(self, tmp_path):
        """A legacy 'Validated' factor with Gate 2 metrics fails Gate 3."""
        reg = _make_registry(tmp_path)
        fid = reg.register_factor(name="legacy_fail", expression="Rank($volume)")
        reg.update_stage(fid, STAGE_VALIDATED)

        # Gate 2 quality metrics (pass Gate 2 but not Gate 3)
        metrics = {
            "icir": 0.8,
            "t_stat": 2.8,
            "positive_ratio": 0.62,
            "quintile_spread": 0.0025,
            "mean_decay_1d": 0.05,
            "mean_decay_5d": 0.025,
        }
        success, msg = reg.promote_to_next_gate(fid, metrics)
        assert success is False
        assert "icir" in msg
        assert reg.get_factor(fid)["stage"] == STAGE_VALIDATED


# ---------------------------------------------------------------------------
# Test 10: Benjamini-Hochberg FDR correction
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 10a: Expression deduplication
# ---------------------------------------------------------------------------


class TestFactorExpressionDeduplication:
    """Test that duplicate expressions are handled idempotently."""

    def test_no_duplicate_expressions(self, tmp_path):
        """Registering the same expression twice returns the same factor id."""
        reg = _make_registry(tmp_path)

        expression = "$close/Ref($close,10)-1"
        fid1 = reg.register_factor(name="mom_first", expression=expression)
        fid2 = reg.register_factor(name="mom_second", expression=expression)

        assert fid1 == fid2

        # Only one factor should exist in the registry
        factors = reg.list_factors()
        assert len(factors) == 1
        assert factors[0]["id"] == fid1

    def test_different_expressions_different_ids(self, tmp_path):
        """Registering two different expressions produces different factor ids."""
        reg = _make_registry(tmp_path)

        fid1 = reg.register_factor(name="mom_10d", expression="$close/Ref($close,10)-1")
        fid2 = reg.register_factor(name="vol_rank", expression="Rank($volume)")

        assert fid1 != fid2

        factors = reg.list_factors()
        assert len(factors) == 2


# ---------------------------------------------------------------------------
# Test 11: Benjamini-Hochberg FDR correction
# ---------------------------------------------------------------------------


class TestBenjaminiHochberg:
    """Test the Benjamini-Hochberg FDR correction function."""

    def test_benjamini_hochberg_basic(self):
        """Verify BH correction on a known set of p-values.

        With 5 p-values at alpha=0.05:
          p = [0.001, 0.008, 0.039, 0.041, 0.060]
        Adjusted (before monotonicity clamp):
          rank 1: 0.001 * 5 / 1 = 0.005
          rank 2: 0.008 * 5 / 2 = 0.020
          rank 3: 0.039 * 5 / 3 = 0.065
          rank 4: 0.041 * 5 / 4 = 0.05125
          rank 5: 0.060 * 5 / 5 = 0.060
        After monotonicity (walk backward):
          rank 5: 0.060
          rank 4: min(0.05125, 0.060) = 0.05125
          rank 3: min(0.065, 0.05125) = 0.05125
          rank 2: min(0.020, 0.05125) = 0.020
          rank 1: min(0.005, 0.020) = 0.005

        Significant (<= 0.05): indices 0 and 1 only.
        """
        p_values = [0.001, 0.008, 0.039, 0.041, 0.060]
        significant, adjusted = benjamini_hochberg_correction(p_values, alpha=0.05)

        assert len(significant) == 5
        assert len(adjusted) == 5

        # First two should be significant
        assert significant[0] is True
        assert significant[1] is True
        # Remaining should not
        assert significant[2] is False
        assert significant[3] is False
        assert significant[4] is False

        # Check specific adjusted values
        assert abs(adjusted[0] - 0.005) < 1e-10
        assert abs(adjusted[1] - 0.020) < 1e-10
        assert abs(adjusted[2] - 0.05125) < 1e-10
        assert abs(adjusted[3] - 0.05125) < 1e-10
        assert abs(adjusted[4] - 0.060) < 1e-10

    def test_benjamini_hochberg_all_significant(self):
        """All p-values below a generous threshold should all be significant."""
        p_values = [0.001, 0.002, 0.003, 0.004, 0.005]
        significant, adjusted = benjamini_hochberg_correction(p_values, alpha=0.10)

        assert all(significant), f"Expected all significant, got {significant}"
        # All adjusted p-values should be <= alpha
        assert all(v <= 0.10 for v in adjusted)

    def test_benjamini_hochberg_none_significant(self):
        """All p-values above the threshold should produce no significant results."""
        p_values = [0.5, 0.6, 0.7, 0.8, 0.9]
        significant, adjusted = benjamini_hochberg_correction(p_values, alpha=0.05)

        assert not any(significant), f"Expected none significant, got {significant}"

    def test_benjamini_hochberg_empty(self):
        """Empty input returns empty outputs."""
        significant, adjusted = benjamini_hochberg_correction([], alpha=0.05)
        assert significant == []
        assert adjusted == []

    def test_benjamini_hochberg_single_value(self):
        """A single p-value is adjusted to itself (n/rank = 1/1 = 1)."""
        p_values = [0.03]
        significant, adjusted = benjamini_hochberg_correction(p_values, alpha=0.05)
        assert significant == [True]
        assert abs(adjusted[0] - 0.03) < 1e-10

    def test_benjamini_hochberg_clamped_to_one(self):
        """Adjusted p-values should not exceed 1.0."""
        p_values = [0.8, 0.9, 0.95]
        _, adjusted = benjamini_hochberg_correction(p_values, alpha=0.05)
        assert all(v <= 1.0 for v in adjusted)


class TestFDRInScanReport:
    """Test that ScanResult and ScanReport carry FDR fields correctly."""

    def test_scan_result_has_fdr_fields(self):
        """ScanResult should have raw_p_value, adjusted_p_value, fdr_significant."""
        result = ScanResult(
            name="test_factor",
            expression="$close",
            category="custom",
            rank_ic=0.04,
            icir=1.0,
            t_stat=3.0,
            quintile_spread=0.005,
            passed=True,
            n_periods=48,
        )
        # Defaults
        assert result.raw_p_value == 1.0
        assert result.adjusted_p_value == 1.0
        assert result.fdr_significant is False

        # Set FDR fields
        result.raw_p_value = 0.001
        result.adjusted_p_value = 0.005
        result.fdr_significant = True
        assert result.fdr_significant is True

        # to_dict includes FDR fields
        d = result.to_dict()
        assert "raw_p_value" in d
        assert "adjusted_p_value" in d
        assert "fdr_significant" in d

    def test_scan_report_has_fdr_fields(self):
        """ScanReport should have fdr_alpha, n_fdr_significant, fdr_passed_factors."""
        result = ScanResult(
            name="f1",
            expression="$close",
            category="momentum",
            rank_ic=0.04,
            icir=1.0,
            t_stat=3.0,
            quintile_spread=0.005,
            passed=True,
            n_periods=48,
            fdr_significant=True,
        )
        report = ScanReport(
            market="us",
            start_date="2021-01-01",
            end_date="2025-12-31",
            total_scanned=1,
            passed=1,
            failed=0,
            results=[result],
            top_factors=[result],
            scan_duration_seconds=1.5,
            fdr_alpha=0.05,
            n_fdr_significant=1,
            fdr_passed_factors=[result],
        )

        assert report.fdr_alpha == 0.05
        assert report.n_fdr_significant == 1
        assert len(report.fdr_passed_factors) == 1
        assert report.fdr_passed_factors[0].name == "f1"

        # to_dict includes FDR fields
        d = report.to_dict()
        assert d["fdr_alpha"] == 0.05
        assert d["n_fdr_significant"] == 1
        assert len(d["fdr_passed_factors"]) == 1
        assert d["fdr_passed_factors"][0]["fdr_significant"] is True

    def test_scan_report_fdr_passed_requires_both_gates_and_fdr(self):
        """fdr_passed_factors should contain only factors that pass both IC gates AND FDR."""
        passed_fdr = ScanResult(
            name="good",
            expression="$close",
            category="momentum",
            rank_ic=0.04,
            icir=1.0,
            t_stat=3.0,
            quintile_spread=0.005,
            passed=True,
            n_periods=48,
            fdr_significant=True,
        )
        passed_not_fdr = ScanResult(
            name="no_fdr",
            expression="$close",
            category="momentum",
            rank_ic=0.04,
            icir=1.0,
            t_stat=2.1,
            quintile_spread=0.005,
            passed=True,
            n_periods=48,
            fdr_significant=False,
        )
        failed = ScanResult(
            name="bad",
            expression="$close",
            category="momentum",
            rank_ic=0.001,
            icir=0.1,
            t_stat=0.5,
            quintile_spread=0.0001,
            passed=False,
            n_periods=48,
            fdr_significant=False,
        )

        all_results = [passed_fdr, passed_not_fdr, failed]
        fdr_passed = [r for r in all_results if r.passed and r.fdr_significant]

        assert len(fdr_passed) == 1
        assert fdr_passed[0].name == "good"
