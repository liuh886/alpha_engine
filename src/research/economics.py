"""Canonical economic primitives for governed research evaluation.

Keep these functions deliberately small. Strategy selection, portfolio construction,
window policy and promotion gates belong to their owning execution/evaluation layers.
"""

from __future__ import annotations

from math import prod


def compound_returns(values: list[float]) -> float:
    """Compound period returns into terminal return using one canonical definition."""

    return prod(1.0 + value for value in values) - 1.0


def relative_excess(strategy_return: float, benchmark_return: float) -> float:
    """Return strategy terminal wealth relative to benchmark terminal wealth."""

    return (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0
