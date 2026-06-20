"""Minimal strategy execution engine.

This is a contract-first engine for deterministic tests. Existing Qlib
strategies can later become adapters over this interface without changing the
interface itself.
"""

from __future__ import annotations

from src.execution.models import (
    ExecutionPlan,
    ExecutionRequest,
    ExecutionResult,
    Order,
    OrderSide,
    PositionChange,
    RiskViolation,
)


class StrategyExecutionEngine:
    """Build a target-weight execution plan from scores and risk policy."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        tradable = request.market.tradable
        eligible = [
            (instrument, score)
            for instrument, score in request.signals.scores.items()
            if tradable.get(instrument, True)
        ]
        eligible.sort(key=lambda item: item[1], reverse=True)

        target_names = [instrument for instrument, _ in eligible[: request.config.topk]]
        max_weight = request.risk_policy.max_position_weight
        target_weight = min(max_weight, 1.0 / max(1, len(target_names))) if target_names else 0.0
        target_weights = {instrument: target_weight for instrument in target_names}

        violations = self._risk_violations(request, target_weights)
        orders = self._orders(request.portfolio.positions, target_weights)
        changes = [
            PositionChange(
                instrument=order.instrument,
                from_weight=request.portfolio.positions.get(order.instrument, 0.0),
                to_weight=order.target_weight,
            )
            for order in orders
        ]

        plan = ExecutionPlan(
            asof_date=request.signals.asof_date,
            target_weights=target_weights,
        )
        return ExecutionResult(
            plan=plan,
            orders=orders,
            risk_violations=violations,
            position_changes=changes,
            explanation=(
                f"Selected top {len(target_names)} tradable instruments by score "
                f"with max weight {max_weight:.2%}."
            ),
        )

    @staticmethod
    def _orders(current: dict[str, float], target: dict[str, float]) -> list[Order]:
        orders: list[Order] = []
        instruments = sorted(set(current) | set(target))
        for instrument in instruments:
            old = current.get(instrument, 0.0)
            new = target.get(instrument, 0.0)
            if abs(old - new) <= 1e-12:
                continue
            side = OrderSide.BUY if new > old else OrderSide.SELL
            orders.append(
                Order(
                    instrument=instrument,
                    side=side,
                    target_weight=new,
                    reason="target_weight_change",
                )
            )
        return orders

    @staticmethod
    def _risk_violations(
        request: ExecutionRequest,
        target_weights: dict[str, float],
    ) -> list[RiskViolation]:
        violations: list[RiskViolation] = []
        if request.config.topk <= 0:
            violations.append(
                RiskViolation(
                    code="invalid_topk",
                    message="ExecutionConfig.topk must be positive.",
                    severity="critical",
                )
            )
        if not request.risk_policy.allow_shorts:
            for instrument, weight in request.portfolio.positions.items():
                if weight < 0:
                    violations.append(
                        RiskViolation(
                            code="short_position",
                            message="Short positions are not allowed by the risk policy.",
                            severity="critical",
                            instrument=instrument,
                        )
                    )
        for instrument, weight in target_weights.items():
            if weight > request.risk_policy.max_position_weight:
                violations.append(
                    RiskViolation(
                        code="position_weight_limit",
                        message="Target weight exceeds max_position_weight.",
                        severity="critical",
                        instrument=instrument,
                    )
                )
        return violations

