"""Notebook-first research lab contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CANONICAL_10D_RETURN_EXPR = "Ref($close, -10) / $close - 1"


@dataclass(frozen=True)
class ResearchSessionConfig:
    market: str
    symbols: list[str]
    benchmark: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    holding_days: int = 10
    rebalance_days: int = 10
    topk: int = 15
    label_type: str = "raw_10d_return"
    model_type: str = "lgbm_regressor"
    factor_expressions: list[str] = field(default_factory=list)
    return_expression: str = CANONICAL_10D_RETURN_EXPR
    factor_selection_path: str = "data/factor_selection.json"
    experiment_id: str = ""

    def __post_init__(self) -> None:
        if self.holding_days != 10:
            raise ValueError("holding_days must be 10")
        if self.rebalance_days != 10:
            raise ValueError("rebalance_days must be 10")
        if self.topk <= 0:
            raise ValueError("topk must be positive")
        if not self.symbols:
            raise ValueError("symbols must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
