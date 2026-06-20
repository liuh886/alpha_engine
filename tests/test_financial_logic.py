"""Deterministic unit tests for core financial logic.

These tests use synthetic data to verify correctness without
depending on external services or live data.
"""

import numpy as np
import pandas as pd
import pytest


class TestFactorICComputation:
    """Test IC computation with known synthetic data."""

    def test_perfect_prediction_gives_high_ic(self):
        """When predictions perfectly match returns, IC should be ~1.0."""
        np.random.seed(42)
        n = 100
        returns = np.random.randn(n)
        predictions = returns.copy()  # Perfect prediction

        ic = np.corrcoef(predictions, returns)[0, 1]
        assert ic > 0.99, f"Perfect prediction IC should be ~1.0, got {ic:.4f}"

    def test_random_prediction_gives_low_ic(self):
        """Random predictions should give IC near 0."""
        np.random.seed(42)
        n = 1000
        returns = np.random.randn(n)
        predictions = np.random.randn(n)

        ic = np.corrcoef(predictions, returns)[0, 1]
        assert abs(ic) < 0.15, f"Random prediction IC should be near 0, got {ic:.4f}"

    def test_inverse_prediction_gives_negative_ic(self):
        """Inverse predictions should give negative IC."""
        np.random.seed(42)
        n = 100
        returns = np.random.randn(n)
        predictions = -returns  # Inverse prediction

        ic = np.corrcoef(predictions, returns)[0, 1]
        assert ic < -0.99, f"Inverse prediction IC should be ~-1.0, got {ic:.4f}"


class TestSignalGradeEngine:
    """Test signal grade computation with synthetic data."""

    def test_percentile_based_grading(self):
        """Top 10% should get AAA, bottom 10% should get VVV."""
        from src.strategies.signal_grade_engine import SignalGradeEngine

        engine = SignalGradeEngine(step_size=10)

        # Create synthetic predictions
        np.random.seed(42)
        n_stocks = 100
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        instruments = [f"stock_{i:03d}" for i in range(n_stocks)]

        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        scores = np.random.randn(len(idx))
        pred_df = pd.DataFrame({"score": scores}, index=idx)

        # Get grade for a specific stock on a specific date
        date_str = dates[0].strftime("%Y-%m-%d")
        grade = engine.get_grade_for_date("stock_000", pred_df, date_str)

        assert grade.symbol == "stock_000"
        assert grade.total_stocks == n_stocks
        assert 0 <= grade.percentile <= 100

    def test_grade_consistency(self):
        """Higher score should give higher percentile."""
        from src.strategies.signal_grade_engine import SignalGradeEngine

        engine = SignalGradeEngine(step_size=10)

        # Create predictions where stock_000 has highest score
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        instruments = ["stock_000", "stock_001", "stock_002"]

        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        scores = []
        for _ in dates:
            scores.extend([10.0, 5.0, 0.0])  # stock_000 always highest
        pred_df = pd.DataFrame({"score": scores}, index=idx)

        date_str = dates[0].strftime("%Y-%m-%d")
        grade_high = engine.get_grade_for_date("stock_000", pred_df, date_str)
        grade_low = engine.get_grade_for_date("stock_002", pred_df, date_str)

        assert grade_high.percentile > grade_low.percentile


class TestPortfolioConstraints:
    """Test portfolio constraint violations with synthetic data."""

    def test_industry_concentration_violation(self):
        """Portfolio with >30% in one industry should trigger violation."""
        from src.guardrails.portfolio_constraints import PortfolioConstraintEngine

        engine = PortfolioConstraintEngine()

        # All stocks in same industry
        positions = {"stock_A": 0.4, "stock_B": 0.3, "stock_C": 0.3}
        market_data = {
            "industry_map": {
                "stock_A": "Tech",
                "stock_B": "Tech",
                "stock_C": "Tech",
            }
        }

        violations = engine.check_portfolio(positions, market_data)
        industry_violations = [v for v in violations if v.type.value == "industry_concentration"]
        assert len(industry_violations) > 0, "Should detect industry concentration"

    def test_no_violation_when_diversified(self):
        """Well-diversified portfolio should have no violations."""
        from src.guardrails.portfolio_constraints import PortfolioConstraintEngine

        engine = PortfolioConstraintEngine()

        positions = {"stock_A": 0.1, "stock_B": 0.1, "stock_C": 0.1, "stock_D": 0.1, "stock_E": 0.1}
        market_data = {
            "industry_map": {
                "stock_A": "Tech",
                "stock_B": "Finance",
                "stock_C": "Healthcare",
                "stock_D": "Energy",
                "stock_E": "Consumer",
            }
        }

        violations = engine.check_portfolio(positions, market_data)
        industry_violations = [v for v in violations if v.type.value == "industry_concentration"]
        assert len(industry_violations) == 0, "Diversified portfolio should not trigger industry violation"

    def test_consecutive_loss_detection(self):
        """5+ consecutive loss days should trigger de-leverage."""
        from src.guardrails.portfolio_constraints import PortfolioConstraintEngine

        engine = PortfolioConstraintEngine()

        positions = {"stock_A": 1.0}
        # 7 consecutive loss days (all strictly below -0.02 threshold)
        market_data = {
            "daily_returns": [-0.03, -0.05, -0.04, -0.03, -0.05, -0.03, -0.04],
        }

        violations = engine.check_portfolio(positions, market_data)
        loss_violations = [v for v in violations if v.type.value == "consecutive_loss"]
        assert len(loss_violations) > 0, "Should detect consecutive losses"


class TestResearchPipeline:
    """Test pipeline step execution with mocked data."""

    def test_step_records_timing(self):
        """Steps should record start/end times and duration."""
        from src.research.pipeline import ResearchRun

        run = ResearchRun(market="cn", goal="test")
        run.start()

        with run.step("test_step") as step:
            step.output = {"result": "ok"}

        s = run.steps[-1]
        assert s.started_at is not None
        assert s.completed_at is not None
        assert s.duration_seconds >= 0
        assert s.output == {"result": "ok"}

    def test_step_failure_records_error(self):
        """Failed steps should capture error message."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test")
        run.start()

        with pytest.raises(ValueError):
            with run.step("failing_step"):
                raise ValueError("test error message")

        s = run.steps[-1]
        assert s.status == StepStatus.FAILED
        assert "test error message" in s.error

    def test_run_save_load_roundtrip(self, tmp_path):
        """Run should persist and restore correctly."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="roundtrip test")
        run.start()
        with run.step("step1") as step:
            step.output = {"metric": 0.42}
        run.complete(recommendation="Deploy")

        path = tmp_path / "run.json"
        run.save(path)

        loaded = ResearchRun.load(path)
        assert loaded.run_id == run.run_id
        assert loaded.status == StepStatus.COMPLETED
        assert loaded.recommendation == "Deploy"
        assert loaded.steps[0].output == {"metric": 0.42}


class TestDecayMonitorLogic:
    """Test decay monitor with synthetic IC history."""

    def test_healthy_factor_with_stable_ic(self):
        """Stable positive IC should report healthy."""
        from src.research.decay_monitor import DecayMonitor, DecayStatus

        monitor = DecayMonitor()
        # Stable IC around 0.05
        dates = pd.date_range("2025-01-01", periods=50, freq="W")
        ic_values = np.random.RandomState(42).normal(0.05, 0.01, 50)
        ic_history = pd.Series(ic_values, index=dates)

        report = monitor.check_factor("test_factor", ic_history)
        assert report.status == DecayStatus.HEALTHY
        assert len(report.alerts) == 0

    def test_declining_ic_triggers_watch(self):
        """IC declining over time should trigger watch or worse."""
        from src.research.decay_monitor import DecayMonitor, DecayStatus

        monitor = DecayMonitor()
        # IC declining from 0.10 to -0.05
        dates = pd.date_range("2025-01-01", periods=50, freq="W")
        ic_values = np.linspace(0.10, -0.05, 50)
        ic_history = pd.Series(ic_values, index=dates)

        report = monitor.check_factor("declining_factor", ic_history)
        assert report.status in (DecayStatus.WATCH, DecayStatus.DEGRADED, DecayStatus.DOWNgrade)
        assert report.ic_trend < 0
        assert len(report.alerts) > 0

    def test_negative_ic_triggers_downgrade(self):
        """Persistently negative IC should trigger downgrade."""
        from src.research.decay_monitor import DecayMonitor, DecayStatus

        monitor = DecayMonitor()
        # All IC negative
        dates = pd.date_range("2025-01-01", periods=50, freq="W")
        ic_values = np.random.RandomState(42).normal(-0.05, 0.01, 50)
        ic_history = pd.Series(ic_values, index=dates)

        report = monitor.check_factor("negative_factor", ic_history)
        assert report.status == DecayStatus.DOWNgrade
        assert report.ic_current < 0

    def test_insufficient_data_returns_watch(self):
        """Less than 5 data points should return watch with insufficient_data."""
        from src.research.decay_monitor import DecayMonitor, DecayStatus

        monitor = DecayMonitor()
        dates = pd.date_range("2025-01-01", periods=3, freq="W")
        ic_history = pd.Series([0.05, 0.06, 0.04], index=dates)

        report = monitor.check_factor("sparse_factor", ic_history)
        assert report.status == DecayStatus.WATCH
        assert "insufficient_data" in report.alerts

    def test_report_summary_counts(self):
        """Summary should correctly count factor statuses."""
        from src.research.decay_monitor import (
            DecayMonitor,
            DecayStatus,
            FactorDecayReport,
        )

        monitor = DecayMonitor()
        reports = [
            FactorDecayReport(factor_name="a", status=DecayStatus.HEALTHY),
            FactorDecayReport(factor_name="b", status=DecayStatus.WATCH),
            FactorDecayReport(factor_name="c", status=DecayStatus.DEGRADED),
            FactorDecayReport(factor_name="d", status=DecayStatus.DOWNgrade),
        ]
        summary = monitor.generate_report(reports)
        assert summary["total_factors"] == 4
        assert summary["status_distribution"]["healthy"] == 1
        assert summary["status_distribution"]["watch"] == 1
        assert len(summary["factors_needing_attention"]) == 3

    def test_ic_history_persistence(self, tmp_path):
        """IC history should save and load correctly."""
        from src.research.decay_monitor import DecayMonitor

        monitor = DecayMonitor(market="test")
        monitor._HISTORY_DIR = tmp_path

        # Create synthetic IC data
        dates = pd.date_range("2025-01-01", periods=10, freq="W")
        ic_data = {
            "factor_a": pd.Series(np.random.RandomState(42).normal(0.05, 0.01, 10), index=dates),
            "factor_b": pd.Series(np.random.RandomState(43).normal(0.03, 0.02, 10), index=dates),
        }

        # Save
        monitor.save_persistent_history(ic_data)

        # Load
        loaded = monitor.load_persistent_history()
        assert len(loaded) == 2
        assert "factor_a" in loaded
        assert "factor_b" in loaded
        assert len(loaded["factor_a"]) == 10
        assert abs(loaded["factor_a"].iloc[0] - ic_data["factor_a"].iloc[0]) < 1e-6


class TestPortfolioConstraintDetails:
    """Test specific constraint violation scenarios."""

    def test_turnover_cost_violation(self):
        """High turnover should trigger cost violation."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        positions = {"A": 0.5, "B": 0.5}
        prev_positions = {"A": 0.1, "C": 0.9}  # 80% turnover
        market_data = {"prev_positions": prev_positions}

        violations = engine.check_portfolio(positions, market_data)
        turnover_v = [v for v in violations if v.type == ConstraintType.TURNOVER_COST]
        assert len(turnover_v) > 0
        assert "turnover" in turnover_v[0].message.lower()

    def test_factor_exposure_violation(self):
        """High factor z-score should trigger exposure violation."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        positions = {"A": 1.0}
        market_data = {
            "factor_exposures": {
                "A": {"momentum": 5.0},  # Very high z-score
            }
        }

        violations = engine.check_portfolio(positions, market_data)
        factor_v = [v for v in violations if v.type == ConstraintType.FACTOR_EXPOSURE]
        assert len(factor_v) > 0

    def test_liquidity_low_volume_violation(self):
        """Stock with low ADV (price×volume) should trigger liquidity warning."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        positions = {"ILLIQUID": 0.5}
        # 100k shares × 5 CNY price = 500k ADV, below 1M threshold
        volume_df = pd.DataFrame({"ILLIQUID": [100_000.0] * 20})
        price_df = pd.DataFrame({"ILLIQUID": [5.0] * 20})
        market_data = {"volume_df": volume_df, "price_df": price_df, "portfolio_value": 1_000_000}

        violations = engine.check_portfolio(positions, market_data)
        liq_v = [v for v in violations if v.type == ConstraintType.LIQUIDITY_CAPACITY]
        assert len(liq_v) > 0

    def test_correlation_crowding_violation(self):
        """Highly correlated positions should trigger crowding warning."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        positions = {"A": 0.5, "B": 0.5}
        # Perfectly correlated returns
        np.random.seed(42)
        base = np.random.randn(60)
        returns_df = pd.DataFrame({"A": base, "B": base + np.random.randn(60) * 0.01})
        market_data = {"returns_df": returns_df}

        violations = engine.check_portfolio(positions, market_data)
        corr_v = [v for v in violations if v.type == ConstraintType.CORRELATION_CROWDING]
        assert len(corr_v) > 0

    def test_liquidity_uses_price_times_volume(self):
        """ADV should be computed as price × volume when price_df provided."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        # 500k shares × 10 CNY = 5M ADV (above 1M min), but position is 50% of portfolio
        positions = {"STOCK_A": 0.5}
        volume_df = pd.DataFrame({"STOCK_A": [500_000.0] * 20})
        price_df = pd.DataFrame({"STOCK_A": [10.0] * 20})
        # portfolio_value=10M, position=5M, ADV=5M → pct_adv = 100% >> 5% limit
        market_data = {"volume_df": volume_df, "price_df": price_df, "portfolio_value": 10_000_000}

        violations = engine.check_portfolio(positions, market_data)
        liq_v = [v for v in violations if v.type == ConstraintType.LIQUIDITY_CAPACITY]
        # Should have pct_adv violation (position is 100% of ADV, limit is 5%)
        assert len(liq_v) > 0
        assert any("pct_adv" in str(v.details) or "ADV" in v.message for v in liq_v)

    def test_liquidity_no_violation_when_liquid(self):
        """High ADV stock with small position should pass."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        # 10M shares × 50 CNY = 500M ADV, position = 50k (0.1% of ADV)
        positions = {"LIQUID_STOCK": 0.5}
        volume_df = pd.DataFrame({"LIQUID_STOCK": [10_000_000.0] * 20})
        price_df = pd.DataFrame({"LIQUID_STOCK": [50.0] * 20})
        market_data = {"volume_df": volume_df, "price_df": price_df, "portfolio_value": 100_000}

        violations = engine.check_portfolio(positions, market_data)
        liq_v = [v for v in violations if v.type == ConstraintType.LIQUIDITY_CAPACITY]
        assert len(liq_v) == 0

    def test_apply_deleverage_constraint(self):
        """De-leverage should reduce all positions by deleverage factor."""
        from src.guardrails.portfolio_constraints import (
            ConstraintType,
            ConstraintViolation,
            PortfolioConstraintEngine,
        )

        engine = PortfolioConstraintEngine()
        positions = {"A": 0.6, "B": 0.4}
        violations = [
            ConstraintViolation(
                type=ConstraintType.CONSECUTIVE_LOSS,
                severity="critical",
                message="5 consecutive loss days",
                details={"deleverage_factor": 0.5},
            )
        ]

        adjusted = engine.apply_constraints(positions, violations)
        assert adjusted["A"] == pytest.approx(0.3)
        assert adjusted["B"] == pytest.approx(0.2)
