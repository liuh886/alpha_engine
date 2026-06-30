"""Core interface layer — pure functions, notebook-callable, no side effects.

Import pattern:
    from src.core.signals import generate_scores
    from src.core.selection import select_topk, select_bottomk
    from src.core.portfolio import build_rolling_portfolio
    from src.core.metrics import compute_spread, compute_ic_series
"""
from .signals import generate_scores
from .selection import select_topk, select_bottomk
from .portfolio import build_rolling_portfolio
from .metrics import compute_spread, compute_ic_series

__all__ = [
    "generate_scores",
    "select_topk",
    "select_bottomk",
    "build_rolling_portfolio",
    "compute_spread",
    "compute_ic_series",
]
