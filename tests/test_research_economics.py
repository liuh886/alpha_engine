from __future__ import annotations

import math

from src.research.economics import compound_returns, relative_excess


def test_compound_returns_matches_direct_wealth_math() -> None:
    values = [0.10, -0.05, 0.02, 0.00]

    observed = compound_returns(values)
    expected = math.prod(1.0 + value for value in values) - 1.0

    assert observed == expected


def test_compound_returns_handles_empty_series_as_zero_return() -> None:
    assert compound_returns([]) == 0.0


def test_relative_excess_matches_terminal_wealth_ratio() -> None:
    strategy_return = 0.18
    benchmark_return = 0.10

    assert relative_excess(strategy_return, benchmark_return) == (
        (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0
    )
