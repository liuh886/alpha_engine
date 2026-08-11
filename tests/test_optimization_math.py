"""Tests for src.optimization.math."""
import pytest
from src.optimization.math import (
    compound_returns, relative_excess, max_drawdown, strongest_window_share,
    turnover_cost, WindowResult, AggregateResult, check_gates, all_gates_pass,
)


class TestCompoundReturns:
    def test_positive(self): assert abs(compound_returns([0.10, 0.20]) - 0.32) < 1e-10
    def test_mixed(self): assert abs(compound_returns([0.10, -0.05, 0.20]) - 0.254) < 1e-10
    def test_empty(self): assert compound_returns([]) == 0.0


class TestRelativeExcess:
    def test_positive(self): assert abs(relative_excess(0.30, 0.15) - 0.13043478260869565) < 1e-10
    def test_bench_neg(self): assert abs(relative_excess(0.0, -0.10) - 0.1111111111111111) < 1e-10
    def test_bench_loss(self): assert relative_excess(0.0, -1.0) == 0.0


class TestMaxDrawdown:
    def test_simple(self): assert abs(max_drawdown([1.0, 1.1, 0.9, 1.2]) - (-0.18181818181818177)) < 1e-10
    def test_none(self): assert max_drawdown([1.0, 1.1, 1.2]) == 0.0
    def test_severe(self): assert abs(max_drawdown([1.0, 0.5]) - (-0.5)) < 1e-10
    def test_empty(self): assert max_drawdown([]) == 0.0


class TestStrongestWindowShare:
    def test_equal(self): assert abs(strongest_window_share([0.1, 0.1, 0.1]) - 0.3333333333333333) < 1e-10
    def test_one(self): assert strongest_window_share([-0.10, 0.05, -0.20]) == 1.0


class TestTurnoverCost:
    def test_entry(self):
        to, cost = turnover_cost({"A": 0.6, "B": 0.4}, None, 20.0)
        assert abs(to - 1.0) < 1e-10 and abs(cost - 0.002) < 1e-10
    def test_partial(self):
        to, cost = turnover_cost({"A": 0.6, "B": 0.4}, {"A": 0.5, "B": 0.5}, 20.0)
        assert abs(to - 0.2) < 1e-10 and abs(cost - 0.0004) < 1e-10
    def test_rotation(self):
        to, cost = turnover_cost({"C": 1.0}, {"A": 1.0}, 10.0)
        assert abs(to - 2.0) < 1e-10


class TestGateChecking:
    def _make(self, cid, excesses, dds, stress):
        windows = {}
        for i, (exc, dd) in enumerate(zip(excesses, dds)):
            w = WindowResult(f"W{i}", exc, exc * 0.3, dd, 12, 8)
            windows[f"W{i}"] = w
        return AggregateResult(cid, windows, stress)

    def test_all_pass(self):
        bl = self._make("bl", [0.10, 0.15, 0.08, 0.20], [-0.05, -0.08, -0.30, -0.10], {20: 0.60, 60: 0.45})
        ch = self._make("ch", [0.12, 0.18, 0.10, 0.22], [-0.04, -0.07, -0.26, -0.09], {20: 0.72, 60: 0.55})
        assert all_gates_pass(check_gates(ch, bl))

    def test_dd_fails(self):
        bl = self._make("bl", [0.10], [-0.30], {20: 0.05, 60: 0.02})
        ch = self._make("ch", [0.12], [-0.28], {20: 0.07, 60: 0.03})
        assert not check_gates(ch, bl)["dd_improves_3pp_or_above_m22"]

    def test_dd_above_m22(self):
        bl = self._make("bl", [0.10], [-0.30], {20: 0.05, 60: 0.02})
        ch = self._make("ch", [0.12], [-0.21], {20: 0.07, 60: 0.03})
        assert check_gates(ch, bl)["dd_improves_3pp_or_above_m22"]

    def test_60bps_missing(self):
        bl = self._make("bl", [0.10], [-0.30], {20: 0.05})
        ch = self._make("ch", [0.12], [-0.21], {20: 0.07})
        assert not check_gates(ch, bl)["positive_60bps_excess"]
