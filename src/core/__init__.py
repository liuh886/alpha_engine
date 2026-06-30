"""Notebook-friendly core interfaces for strategy research."""

from .metrics import compute_spread_metrics
from .portfolio import build_fixed_rebalance_schedule, build_rolling_portfolio
from .selection import GuardrailInputs, select_bottomn, select_topn
from .signals import ScoreGenerationError, generate_scores, load_model

__all__ = [
    "GuardrailInputs",
    "ScoreGenerationError",
    "build_fixed_rebalance_schedule",
    "build_rolling_portfolio",
    "compute_spread_metrics",
    "generate_scores",
    "load_model",
    "select_bottomn",
    "select_topn",
]
