"""Narrow fixed-10D evaluator contexts.

Execution contracts own research semantics. Evaluators consume only the fields
needed to compare score frames and serialize one window's context. Legacy
``ResearchSessionConfig`` remains structurally compatible for notebooks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR


@runtime_checkable
class TenDayEvaluationConfig(Protocol):
    """Structural interface required by the fixed-10D evaluator."""

    market: str
    topk: int
    rebalance_days: int
    experiment_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable evaluator context."""


@dataclass(frozen=True)
class SpecBoundEvaluationContext:
    """One evaluator window derived from a spec-bound execution plan."""

    market: str
    symbols: tuple[str, ...]
    benchmark: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    holding_days: int
    rebalance_days: int
    topk: int
    model_type: str
    factor_expressions: tuple[str, ...]
    return_expression: str
    experiment_id: str
    semantic_source: str = "spec_bound_execution"

    def __post_init__(self) -> None:
        if self.holding_days != 10:
            raise ValueError("holding_days must be 10")
        if self.rebalance_days != 10:
            raise ValueError("rebalance_days must be 10")
        if self.topk <= 0:
            raise ValueError("topk must be positive")
        if not self.symbols:
            raise ValueError("symbols must not be empty")
        if self.return_expression != CANONICAL_10D_RETURN_EXPR:
            raise ValueError(
                "spec-bound evaluation requires the canonical raw 10D return expression"
            )
        if self.semantic_source != "spec_bound_execution":
            raise ValueError("semantic_source must be 'spec_bound_execution'")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = list(self.symbols)
        payload["factor_expressions"] = list(self.factor_expressions)
        return payload
