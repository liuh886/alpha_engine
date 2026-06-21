"""Domain models for strategy execution.

These models are intentionally independent of Qlib so ordinary and vectorized
strategy adapters can be compared through one stable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class SignalFrame:
    """Scores for instruments at one decision point."""

    asof_date: str
    scores: dict[str, float]


@dataclass(frozen=True)
class PortfolioState:
    """Current portfolio weights and available cash."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Market data needed to turn signals into an execution plan."""

    prices: dict[str, float] = field(default_factory=dict)
    tradable: dict[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskPolicy:
    """Execution-time risk limits."""

    max_position_weight: float = 0.15
    allow_shorts: bool = False


@dataclass(frozen=True)
class ExecutionConfig:
    """Strategy execution configuration."""

    topk: int = 5
    rebalance: bool = True


@dataclass(frozen=True)
class Order:
    instrument: str
    side: OrderSide
    target_weight: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "side": self.side.value,
            "target_weight": self.target_weight,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiskViolation:
    code: str
    message: str
    severity: str = "warning"
    instrument: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "instrument": self.instrument,
        }


@dataclass(frozen=True)
class PositionChange:
    instrument: str
    from_weight: float
    to_weight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "from_weight": self.from_weight,
            "to_weight": self.to_weight,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    asof_date: str
    target_weights: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asof_date": self.asof_date,
            "target_weights": dict(self.target_weights),
        }


@dataclass(frozen=True)
class ExecutionRequest:
    signals: SignalFrame
    portfolio: PortfolioState
    market: MarketDataSnapshot
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    config: ExecutionConfig = field(default_factory=ExecutionConfig)


@dataclass(frozen=True)
class ExecutionResult:
    plan: ExecutionPlan
    orders: list[Order]
    risk_violations: list[RiskViolation]
    position_changes: list[PositionChange]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "orders": [order.to_dict() for order in self.orders],
            "risk_violations": [violation.to_dict() for violation in self.risk_violations],
            "position_changes": [change.to_dict() for change in self.position_changes],
            "explanation": self.explanation,
        }
