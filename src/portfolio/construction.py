"""Risk-constrained portfolio construction (T47.3).

Transforms qualified model signals into deterministic target weights under
configurable position, sector, concentration, turnover, liquidity, cash,
drawdown and transaction-cost constraints, and returns an explainable advisory
ExecutionPlan.

Invariants:

- identical inputs produce byte-identical plans (plan identity is a SHA-256 of
  the canonical input payload);
- every candidate signal receives exactly one decision with an explicit reason;
- infeasible constraint sets fail closed instead of being silently relaxed;
- total weights, cash, turnover and exposure reconcile numerically before a
  plan is returned;
- this module is the single authority for portfolio rules: frontends and
  adapters consume its output and never re-implement selection or sizing.

All outputs are advisory research artifacts: ``research_only=True`` and
``trade_ready=False`` are stamped into every plan.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PortfolioConstructionError",
    "QualifiedSignal",
    "PortfolioRiskState",
    "ConstructionConstraints",
    "WeightDecision",
    "AdvisoryExecutionPlan",
    "PortfolioConstructor",
]

SCHEMA_VERSION = "portfolio_construction_advisory_v1"
_TOLERANCE = 1e-9


class PortfolioConstructionError(Exception):
    """Raised when a plan cannot be produced; the plan fails closed."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class QualifiedSignal:
    """One qualified cross-sectional signal entering construction."""

    instrument: str
    score: float
    sector: str | None = None
    price: float | None = None
    avg_daily_value: float | None = None
    tradable: bool = True

    def canonical(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "score": self.score,
            "sector": self.sector,
            "price": self.price,
            "avg_daily_value": self.avg_daily_value,
            "tradable": self.tradable,
        }


@dataclass(frozen=True)
class PortfolioRiskState:
    """Current risk condition constraining the plan (CONTEXT.md)."""

    current_drawdown: float = 0.0
    risk_limit_breached: bool = False

    def canonical(self) -> dict[str, Any]:
        return {
            "current_drawdown": self.current_drawdown,
            "risk_limit_breached": self.risk_limit_breached,
        }


@dataclass(frozen=True)
class ConstructionConstraints:
    """Configurable portfolio rules; invalid combinations fail closed."""

    max_positions: int = 15
    target_cash_weight: float = 0.0
    max_position_weight: float = 0.10
    max_names_per_sector: int | None = None
    max_sector_weight: float | None = None
    max_turnover: float | None = None
    min_avg_daily_value: float | None = None
    transaction_cost_bps: float = 20.0
    drawdown_deleverage_threshold: float | None = None
    deleveraged_gross_exposure: float | None = None
    weight_scheme: str = "equal"

    def validate(self) -> None:
        reasons: list[str] = []
        if self.max_positions < 1:
            reasons.append("max_positions must be at least 1")
        if not 0.0 <= self.target_cash_weight < 1.0:
            reasons.append("target_cash_weight must be in [0, 1)")
        if self.max_position_weight <= 0.0:
            reasons.append("max_position_weight must be positive")
        if self.max_names_per_sector is not None and self.max_names_per_sector < 1:
            reasons.append("max_names_per_sector must be at least 1 when set")
        if self.max_sector_weight is not None and (
            self.max_sector_weight <= 0.0 or self.max_sector_weight > 1.0 + _TOLERANCE
        ):
            reasons.append("max_sector_weight must be within (0, 1] when set")
        if self.max_turnover is not None and self.max_turnover < 0.0:
            reasons.append("max_turnover must be non-negative when set")
        if self.min_avg_daily_value is not None and self.min_avg_daily_value < 0.0:
            reasons.append("min_avg_daily_value must be non-negative when set")
        if self.transaction_cost_bps < 0.0:
            reasons.append("transaction_cost_bps must be non-negative")
        if self.drawdown_deleverage_threshold is not None:
            if self.deleveraged_gross_exposure is None:
                reasons.append(
                    "deleveraged_gross_exposure is required with drawdown_deleverage_threshold"
                )
            elif not 0.0 < self.deleveraged_gross_exposure <= 1.0 - self.target_cash_weight + _TOLERANCE:
                reasons.append("deleveraged_gross_exposure must be within (0, 1 - cash]")
        if self.weight_scheme != "equal":
            reasons.append("only the 'equal' weight scheme is supported")
        if reasons:
            raise PortfolioConstructionError(reasons)

    def canonical(self) -> dict[str, Any]:
        return {
            "max_positions": self.max_positions,
            "target_cash_weight": self.target_cash_weight,
            "max_position_weight": self.max_position_weight,
            "max_names_per_sector": self.max_names_per_sector,
            "max_sector_weight": self.max_sector_weight,
            "max_turnover": self.max_turnover,
            "min_avg_daily_value": self.min_avg_daily_value,
            "transaction_cost_bps": self.transaction_cost_bps,
            "drawdown_deleverage_threshold": self.drawdown_deleverage_threshold,
            "deleveraged_gross_exposure": self.deleveraged_gross_exposure,
            "weight_scheme": self.weight_scheme,
        }


@dataclass(frozen=True)
class WeightDecision:
    """The outcome for one candidate signal; exclusions always carry reasons."""

    instrument: str
    score: float
    sector: str | None
    status: str
    weight: float | None
    reason_code: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "score": self.score,
            "sector": self.sector,
            "status": self.status,
            "weight": self.weight,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AdvisoryExecutionPlan:
    """Explainable advisory plan; never a live-trading instruction."""

    plan_id: str
    asof_date: str
    market: str
    model_version_id: str
    data_snapshot_id: str
    champion_id: str | None
    target_weights: dict[str, float]
    cash_weight: float
    gross_exposure: float
    net_exposure: float
    traded_notional_fraction: float
    one_sided_turnover: float
    expected_transaction_cost: float
    decisions: tuple[WeightDecision, ...]
    constraint_snapshot: dict[str, Any]
    reconciliation: dict[str, bool]
    warnings: tuple[str, ...]
    research_only: bool = True
    trade_ready: bool = False

    @property
    def selected_instruments(self) -> list[str]:
        return sorted(self.target_weights)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "asof_date": self.asof_date,
            "market": self.market,
            "model_version_id": self.model_version_id,
            "data_snapshot_id": self.data_snapshot_id,
            "champion_id": self.champion_id,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "advisory_only": True,
            "target_weights": dict(sorted(self.target_weights.items())),
            "cash_weight": self.cash_weight,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "traded_notional_fraction": self.traded_notional_fraction,
            "one_sided_turnover": self.one_sided_turnover,
            "expected_transaction_cost": self.expected_transaction_cost,
            "decisions": [d.to_dict() for d in self.decisions],
            "constraint_snapshot": dict(sorted(self.constraint_snapshot.items())),
            "reconciliation": dict(sorted(self.reconciliation.items())),
            "warnings": list(self.warnings),
        }


@dataclass
class _Accumulator:
    decisions: list[WeightDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PortfolioConstructor:
    """Single authority for advisory portfolio construction rules."""

    def __init__(self, constraints: ConstructionConstraints) -> None:
        constraints.validate()
        self._constraints = constraints

    @property
    def constraints(self) -> ConstructionConstraints:
        return self._constraints

    def build_plan(
        self,
        *,
        asof_date: str,
        signals: list[QualifiedSignal],
        current_weights: dict[str, float] | None = None,
        risk_state: PortfolioRiskState | None = None,
        market: str = "",
        model_version_id: str = "",
        data_snapshot_id: str = "",
        champion_id: str | None = None,
    ) -> AdvisoryExecutionPlan:
        current = dict(current_weights or {})
        risk = risk_state or PortfolioRiskState()

        identity_reasons = [
            note
            for note, value in (
                ("asof_date is required", asof_date),
                ("model_version_id is required for plan identity", model_version_id),
                ("data_snapshot_id is required for plan identity", data_snapshot_id),
            )
            if not value
        ]
        if identity_reasons:
            raise PortfolioConstructionError(identity_reasons)

        ordered = self._validated_signals(signals)
        acc = _Accumulator()
        sector_counts: dict[str, int] = {}
        selected: list[QualifiedSignal] = []

        capacity_reached = False
        for rank, signal in enumerate(ordered):
            decision = self._decide(
                signal,
                rank=rank,
                capacity_reached=capacity_reached,
                sector_counts=sector_counts,
            )
            acc.decisions.append(decision)
            if decision.status == "selected":
                if signal.sector is not None:
                    sector_counts[signal.sector] = sector_counts.get(signal.sector, 0) + 1
                selected.append(signal)
                if len(selected) >= self._constraints.max_positions:
                    capacity_reached = True

        if not selected:
            raise PortfolioConstructionError(
                ["no eligible signals satisfy the configured constraints"]
            )

        gross_target = self._gross_target(risk, acc.warnings)
        weights, trimmed = self._size_and_fit_turnover(selected, current, gross_target)
        if trimmed:
            deferred = gross_target - sum(weights.values())
            acc.warnings.append(
                f"turnover budget bound construction: {len(trimmed)} new name(s) "
                f"deferred to cash ({max(deferred, 0.0):.4f} gross)"
            )

        decisions: list[WeightDecision] = []
        for decision in acc.decisions:
            if decision.status == "selected" and decision.instrument in trimmed:
                decisions.append(
                    WeightDecision(
                        instrument=decision.instrument,
                        score=decision.score,
                        sector=decision.sector,
                        status="removed",
                        weight=None,
                        reason_code="removed_turnover_budget",
                        detail=trimmed[decision.instrument],
                    )
                )
            else:
                decisions.append(decision)

        traded_fraction = sum(
            abs(weights.get(inst, 0.0) - current.get(inst, 0.0)) for inst in set(weights) | set(current)
        )
        turnover_one_sided = traded_fraction / 2.0
        expected_cost = traded_fraction * self._constraints.transaction_cost_bps / 10_000.0
        cash_weight = 1.0 - sum(weights.values())
        gross = sum(weights.values())

        plan = AdvisoryExecutionPlan(
            plan_id=self._plan_id(
                asof_date=asof_date,
                signals=signals,
                current=current,
                risk=risk,
                market=market,
                model_version_id=model_version_id,
                data_snapshot_id=data_snapshot_id,
                champion_id=champion_id,
                trimmed=trimmed,
            ),
            asof_date=asof_date,
            market=market,
            model_version_id=model_version_id,
            data_snapshot_id=data_snapshot_id,
            champion_id=champion_id,
            target_weights=weights,
            cash_weight=cash_weight,
            gross_exposure=gross,
            net_exposure=gross,
            traded_notional_fraction=traded_fraction,
            one_sided_turnover=turnover_one_sided,
            expected_transaction_cost=expected_cost,
            decisions=tuple(decisions),
            constraint_snapshot=self._constraints.canonical(),
            reconciliation={},
            warnings=tuple(acc.warnings),
        )
        object.__setattr__(
            plan,
            "reconciliation",
            self._reconcile(
                plan,
                sector_by_instrument={s.instrument: str(s.sector) for s in signals if s.sector},
                signal_instruments={s.instrument for s in signals},
            ),
        )
        failed = sorted(name for name, ok in plan.reconciliation.items() if not ok)
        if failed:
            raise PortfolioConstructionError(
                [f"plan failed internal reconciliation: {name}" for name in failed]
            )
        return plan

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validated_signals(
        self, signals: list[QualifiedSignal]
    ) -> list[QualifiedSignal]:
        if not signals:
            raise PortfolioConstructionError(["signal list is empty"])
        seen: set[str] = set()
        bad_score: list[str] = []
        missing_sector: list[str] = []
        for signal in signals:
            if signal.instrument in seen:
                raise PortfolioConstructionError(
                    [f"duplicate instrument in signal list: {signal.instrument}"]
                )
            seen.add(signal.instrument)
            if not math.isfinite(signal.score):
                bad_score.append(signal.instrument)
            if self._constraints.max_names_per_sector is not None and not (
                signal.sector and str(signal.sector).strip()
            ):
                missing_sector.append(signal.instrument)
        reasons = []
        if bad_score:
            reasons.append(f"non-finite scores fail closed: {sorted(bad_score)}")
        if missing_sector:
            reasons.append(
                f"sector classification required for every signal when "
                f"max_names_per_sector is set: {sorted(missing_sector)}"
            )
        if reasons:
            raise PortfolioConstructionError(reasons)
        return sorted(signals, key=lambda s: (-s.score, s.instrument))

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _decide(
        self,
        signal: QualifiedSignal,
        *,
        rank: int,
        capacity_reached: bool,
        sector_counts: dict[str, int],
    ) -> WeightDecision:
        base = {
            "instrument": signal.instrument,
            "score": signal.score,
            "sector": signal.sector,
        }
        if not signal.tradable:
            return WeightDecision(**base, status="excluded", weight=None, reason_code="excluded_not_tradable", detail="instrument is not tradable at the decision boundary")
        price_invalid = signal.price is None or not math.isfinite(signal.price) or signal.price <= 0.0
        if price_invalid:
            return WeightDecision(**base, status="excluded", weight=None, reason_code="excluded_not_tradable", detail="missing or non-positive price")
        floor = self._constraints.min_avg_daily_value
        if floor is not None and (signal.avg_daily_value is None or signal.avg_daily_value < floor):
            return WeightDecision(
                **base,
                status="excluded",
                weight=None,
                reason_code="excluded_liquidity_floor",
                detail=f"avg_daily_value {signal.avg_daily_value} below floor {floor}",
            )
        if capacity_reached:
            return WeightDecision(**base, status="excluded", weight=None, reason_code="rank_beyond_capacity", detail=f"rank {rank + 1} beyond max_positions {self._constraints.max_positions}")
        sector_cap = self._constraints.max_names_per_sector
        if sector_cap is not None:
            sector = str(signal.sector)
            count = sector_counts.get(sector, 0)
            if count >= sector_cap:
                return WeightDecision(
                    **base,
                    status="capped",
                    weight=None,
                    reason_code="capped_sector_name_limit",
                    detail=f"sector '{sector}' already holds {count} names (cap {sector_cap})",
                )
        return WeightDecision(**base, status="selected", weight=None, reason_code="selected", detail=f"rank {rank + 1}")

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def _gross_target(
        self, risk: PortfolioRiskState, warnings: list[str]
    ) -> float:
        gross = 1.0 - self._constraints.target_cash_weight
        threshold = self._constraints.drawdown_deleverage_threshold
        if threshold is not None and (
            risk.risk_limit_breached or risk.current_drawdown <= threshold
        ):
            deleveraged = float(self._constraints.deleveraged_gross_exposure)
            if deleveraged < gross:
                warnings.append(
                    f"drawdown {risk.current_drawdown:.4f} breached threshold "
                    f"{threshold:.4f}; gross exposure reduced to {deleveraged:.4f}"
                )
                gross = deleveraged
        return gross

    def _size_and_fit_turnover(
        self,
        selected: list[QualifiedSignal],
        current: dict[str, float],
        gross_target: float,
    ) -> tuple[dict[str, float], dict[str, str]]:
        chosen = list(selected)
        trimmed: dict[str, str] = {}
        per_name = gross_target / len(chosen)

        def weights_with(names: list[QualifiedSignal]) -> dict[str, float]:
            return {signal.instrument: per_name for signal in names}

        def turnover_of(weights: dict[str, float]) -> float:
            universe = set(weights) | set(current)
            return sum(abs(weights.get(i, 0.0) - current.get(i, 0.0)) for i in universe) / 2.0

        cap = self._constraints.max_position_weight
        if per_name > cap + _TOLERANCE:
            raise PortfolioConstructionError(
                [
                    f"infeasible constraints: equal weight {per_name:.6f} exceeds "
                    f"max_position_weight {cap:.6f} for {len(chosen)} names"
                ]
            )

        budget = self._constraints.max_turnover
        if budget is not None:
            while turnover_of(weights_with(chosen)) > budget + _TOLERANCE:
                discretionary = [
                    signal
                    for signal in reversed(chosen)
                    if signal.instrument not in current
                ]
                if not discretionary:
                    raise PortfolioConstructionError(
                        [
                            f"infeasible turnover budget {budget:.6f}: forced exits alone "
                            f"produce turnover {turnover_of(weights_with(chosen)):.6f}"
                        ]
                    )
                dropped = discretionary[0]
                chosen = [s for s in chosen if s.instrument != dropped.instrument]
                trimmed[dropped.instrument] = (
                    f"lowest-conviction new name deferred to cash to satisfy "
                    f"turnover budget {budget}"
                )
        if not chosen:
            raise PortfolioConstructionError(["no positions remain after constraint fitting"])
        return weights_with(chosen), trimmed

    # ------------------------------------------------------------------
    # Identity and reconciliation
    # ------------------------------------------------------------------

    def _plan_id(
        self,
        *,
        asof_date: str,
        signals: list[QualifiedSignal],
        current: dict[str, float],
        risk: PortfolioRiskState,
        market: str,
        model_version_id: str,
        data_snapshot_id: str,
        champion_id: str | None,
        trimmed: dict[str, str],
    ) -> str:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "asof_date": asof_date,
            "market": market,
            "model_version_id": model_version_id,
            "data_snapshot_id": data_snapshot_id,
            "champion_id": champion_id,
            "signals": [s.canonical() for s in sorted(signals, key=lambda x: x.instrument)],
            "current_weights": dict(sorted(current.items())),
            "risk_state": risk.canonical(),
            "constraints": self._constraints.canonical(),
            "trim_decisions": dict(sorted(trimmed.items())),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _reconcile(
        self,
        plan: AdvisoryExecutionPlan,
        *,
        sector_by_instrument: dict[str, str],
        signal_instruments: set[str],
    ) -> dict[str, bool]:
        weights = plan.target_weights
        checks = {
            "weights_sum_with_cash_equals_one": abs(sum(weights.values()) + plan.cash_weight - 1.0) <= 1e-6,
            "weights_within_position_cap": all(0.0 < w <= self._constraints.max_position_weight + 1e-6 for w in weights.values()),
            "position_count_within_limit": len(weights) <= self._constraints.max_positions,
            "sector_name_limits_respected": self._sector_counts_ok(
                [sector_by_instrument[i] for i in weights if i in sector_by_instrument]
            ),
            "turnover_within_budget": self._constraints.max_turnover is None
            or plan.one_sided_turnover <= self._constraints.max_turnover + 1e-6,
            "cash_non_negative": plan.cash_weight >= -_TOLERANCE,
            "every_signal_has_one_decision": {d.instrument for d in plan.decisions} == signal_instruments
            and len(plan.decisions) == len(signal_instruments),
            "selected_decisions_match_weights": {d.instrument for d in plan.decisions if d.status == "selected"} == set(weights),
        }
        expected_cost = plan.traded_notional_fraction * self._constraints.transaction_cost_bps / 10_000.0
        checks["expected_cost_consistent"] = abs(plan.expected_transaction_cost - expected_cost) <= 1e-12
        return checks

    def _sector_counts_ok(self, sectors: list[str]) -> bool:
        cap = self._constraints.max_names_per_sector
        if cap is None:
            return True
        counts: dict[str, int] = {}
        for sector in sectors:
            counts[sector] = counts.get(sector, 0) + 1
        return all(count <= cap for count in counts.values())
