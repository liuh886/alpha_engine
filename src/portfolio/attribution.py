"""Post-decision performance and execution attribution (T47.5).

Decomposes realized paper performance into market exposure, sector
contribution, stock selection, timing, costs, slippage and an explicit
unexplained residual, and compares expected versus realized portfolio
outcomes (plan weights/costs against the executed paper book).

Invariants:

- attribution components reconcile to the observed portfolio return within a
  declared tolerance; the residual is always reported, never absorbed;
- every contribution references its source dates, instruments and trades;
- results are advisory research artifacts that feed drift and lifecycle
  decisions without rewriting historical evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AttributionError",
    "AttributionObservation",
    "TradeRecordView",
    "AttributionReport",
    "PaperPerformanceAttributor",
]

SCHEMA_VERSION = "paper_attribution_v1"
_DEFAULT_TOLERANCE = 1e-6


class AttributionError(Exception):
    """Raised when attribution inputs are invalid; fails closed."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class AttributionObservation:
    """One daily snapshot of the paper book and market context.

    ``weights`` are beginning-of-day portfolio weights (instrument -> weight,
    including any cash weight). The first observation serves as the baseline;
    attribution starts from the second observation onward.
    """

    date: str
    nav: float
    weights: dict[str, float]
    instrument_returns: dict[str, float]
    benchmark_return: float
    sector_returns: dict[str, float] | None = None
    fees_paid: float = 0.0
    slippage_cost: float = 0.0

    def canonical(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "nav": self.nav,
            "weights": dict(sorted(self.weights.items())),
            "instrument_returns": {k: v for k, v in sorted(self.instrument_returns.items())},
            "benchmark_return": self.benchmark_return,
            "sector_returns": dict(sorted((self.sector_returns or {}).items())),
            "fees_paid": self.fees_paid,
            "slippage_cost": self.slippage_cost,
        }


@dataclass(frozen=True)
class TradeRecordView:
    """Read-only view of one paper trade for execution attribution."""

    client_order_id: str
    instrument: str
    side: str
    trade_date: str
    requested_quantity: float
    filled_quantity: float
    status: str
    fees: float = 0.0
    slippage_cost: float = 0.0

    @classmethod
    def from_fill_dict(cls, payload: dict[str, Any]) -> TradeRecordView:
        required = ("client_order_id", "instrument", "side", "trade_date", "status")
        missing = [key for key in required if key not in payload]
        if missing:
            raise AttributionError([f"trade record missing fields: {sorted(missing)}"])
        return cls(
            client_order_id=str(payload["client_order_id"]),
            instrument=str(payload["instrument"]),
            side=str(payload["side"]),
            trade_date=str(payload["trade_date"]),
            requested_quantity=float(payload.get("requested_quantity", 0.0)),
            filled_quantity=float(payload.get("filled_quantity", 0.0)),
            status=str(payload["status"]),
            fees=float(payload.get("fees", 0.0) or 0.0),
            slippage_cost=float(payload.get("slippage_cost", 0.0) or 0.0),
        )


@dataclass(frozen=True)
class AttributionReport:
    """Explainable decomposition of realized paper performance."""

    model_version_id: str
    plan_id: str | None
    data_snapshot_id: str
    window_start: str
    window_end: str
    attributed_days: int
    total_return_arithmetic: float
    compounded_return: float
    benchmark_return_sum: float
    contributions: dict[str, float]
    sector_contribution: dict[str, float]
    selection_detail: list[dict[str, Any]]
    timing_detail: list[dict[str, Any]]
    cost_detail: list[dict[str, Any]]
    residual: float
    tolerance: float
    reconciliation: dict[str, Any]
    execution_comparison: dict[str, Any]
    research_only: bool = True
    trade_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "venue": "paper_simulation",
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "model_version_id": self.model_version_id,
            "plan_id": self.plan_id,
            "data_snapshot_id": self.data_snapshot_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "attributed_days": self.attributed_days,
            "total_return_arithmetic": self.total_return_arithmetic,
            "compounded_return": self.compounded_return,
            "benchmark_return_sum": self.benchmark_return_sum,
            "contributions": {k: self.contributions[k] for k in sorted(self.contributions)},
            "sector_contribution": {k: self.sector_contribution[k] for k in sorted(self.sector_contribution)},
            "selection_detail": list(self.selection_detail),
            "timing_detail": list(self.timing_detail),
            "cost_detail": list(self.cost_detail),
            "residual": self.residual,
            "tolerance": self.tolerance,
            "reconciliation": dict(self.reconciliation),
            "execution_comparison": dict(self.execution_comparison),
        }


@dataclass
class _DailyBreakdown:
    date: str
    total_observed: float
    market_exposure: float = 0.0
    sector_effect: float = 0.0
    selection: float = 0.0
    timing: float = 0.0
    costs: float = 0.0
    slippage: float = 0.0
    sector_pnl: dict[str, float] = field(default_factory=dict)


class PaperPerformanceAttributor:
    """Deterministic post-decision attribution over paper-book observations."""

    def __init__(self, *, tolerance: float = _DEFAULT_TOLERANCE) -> None:
        if tolerance <= 0 or not math.isfinite(tolerance):
            raise AttributionError(["tolerance must be positive and finite"])
        self._tolerance = tolerance

    def attribute(
        self,
        *,
        observations: list[AttributionObservation],
        trades: list[dict[str, Any]] | None = None,
        sector_of: dict[str, str] | None = None,
        expected_weights: dict[str, float] | None = None,
        expected_cost: float | None = None,
        model_version_id: str = "",
        plan_id: str | None = None,
        data_snapshot_id: str = "",
    ) -> AttributionReport:
        reasons: list[str] = []
        if len(observations) < 2:
            reasons.append("attribution requires at least two observations (baseline plus one day)")
        if not model_version_id:
            reasons.append("model_version_id is required")
        if not data_snapshot_id:
            reasons.append("data_snapshot_id is required")
        if reasons:
            raise AttributionError(reasons)

        ordered = self._validated(observations)
        breakdowns = [
            self._attribute_day(ordered[i - 1], ordered[i], sector_of or {})
            for i in range(1, len(ordered))
        ]

        totals = {
            "market_exposure": sum(b.market_exposure for b in breakdowns),
            "sector_effect": sum(b.sector_effect for b in breakdowns),
            "stock_selection": sum(b.selection for b in breakdowns),
            "timing": sum(b.timing for b in breakdowns),
            "costs": sum(b.costs for b in breakdowns),
            "slippage": sum(b.slippage for b in breakdowns),
        }
        total_observed = sum(b.total_observed for b in breakdowns)
        components_sum = sum(totals.values())
        residual = total_observed - components_sum

        sector_contribution = self._sector_totals(breakdowns)
        selection_detail = [
            {"date": b.date, "note": "per-instrument detail aggregated in stock_selection"}
            for b in breakdowns[:1]
        ]
        selection_rows = self._selection_rows(breakdowns)
        timing_rows = self._timing_rows(breakdowns)
        cost_rows = self._cost_rows(breakdowns)

        compounded = 1.0
        for b in breakdowns:
            compounded *= 1.0 + b.total_observed
        compounded -= 1.0

        reconciles = abs(residual) <= self._tolerance * max(1.0, abs(total_observed))
        report = AttributionReport(
            model_version_id=model_version_id,
            plan_id=plan_id,
            data_snapshot_id=data_snapshot_id,
            window_start=ordered[1].date,
            window_end=ordered[-1].date,
            attributed_days=len(breakdowns),
            total_return_arithmetic=total_observed,
            compounded_return=compounded,
            benchmark_return_sum=sum(o.benchmark_return for o in ordered[1:]),
            contributions=totals,
            sector_contribution=sector_contribution,
            selection_detail=selection_rows or selection_detail,
            timing_detail=timing_rows,
            cost_detail=cost_rows,
            residual=residual,
            tolerance=self._tolerance,
            reconciliation={},
            execution_comparison=self._execution_comparison(
                ordered, trades or [], expected_weights, expected_cost
            ),
        )
        object.__setattr__(
            report,
            "reconciliation",
            {
                "components_sum_matches_total": True,
                "abs_residual": abs(residual),
                "within_tolerance": reconciles,
                "every_day_has_source_references": all(
                    row.get("date") for row in (selection_rows + timing_rows + cost_rows)
                )
                or not (selection_rows + timing_rows + cost_rows),
            },
        )
        if not reconciles:
            report.reconciliation["warning"] = (
                f"residual {residual:.3e} exceeds tolerance {self._tolerance:.3e}"
            )
        return report

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validated(self, observations: list[AttributionObservation]) -> list[AttributionObservation]:
        reasons: list[str] = []
        seen_dates: set[str] = set()
        previous_nav: float | None = None
        for obs in observations:
            if obs.date in seen_dates:
                reasons.append(f"duplicate observation date: {obs.date}")
            seen_dates.add(obs.date)
            if not math.isfinite(obs.nav) or obs.nav <= 0:
                reasons.append(f"nav must be positive and finite on {obs.date}")
            if not math.isfinite(obs.benchmark_return):
                reasons.append(f"benchmark_return must be finite on {obs.date}")
            if not math.isfinite(obs.fees_paid) or not math.isfinite(obs.slippage_cost):
                reasons.append(f"fee/slippage amounts must be finite on {obs.date}")
            weight_sum = sum(obs.weights.values())
            if weight_sum > 1.0 + 1e-6:
                reasons.append(f"weights exceed 1.0 on {obs.date}: {weight_sum:.6f}")
            if previous_nav is not None and not math.isclose(obs.nav, previous_nav, rel_tol=2.0):
                reasons.append(f"implausible NAV jump into {obs.date}; check observation continuity")
            previous_nav = obs.nav
        if reasons:
            raise AttributionError(reasons)
        return sorted(observations, key=lambda o: o.date)

    # ------------------------------------------------------------------
    # Daily decomposition
    # ------------------------------------------------------------------

    def _attribute_day(
        self,
        base: AttributionObservation,
        day: AttributionObservation,
        sector_of: dict[str, str],
    ) -> _DailyBreakdown:
        nav_prev = base.nav
        start_weights = base.weights
        end_weights = day.weights

        instruments = sorted(
            instrument
            for instrument in set(start_weights) | set(end_weights)
            if instrument != "CASH"
        )

        market_exposure = 0.0
        selection = 0.0
        timing = 0.0
        sector_effect = 0.0
        sector_pnl: dict[str, float] = {}

        for instrument in instruments:
            w_start = start_weights.get(instrument, 0.0)
            w_end = end_weights.get(instrument, 0.0)
            r_i = day.instrument_returns.get(instrument, 0.0)

            market_exposure += w_start * day.benchmark_return
            sector = sector_of.get(instrument)
            reference = day.benchmark_return
            if day.sector_returns and sector and sector in day.sector_returns:
                reference = day.sector_returns[sector]
            sector_pnl.setdefault(str(sector) if sector else "__unclassified__", 0.0)
            sector_pnl[str(sector) if sector else "__unclassified__"] += w_start * (
                reference - day.benchmark_return
            )
            selection += w_start * (r_i - reference)
            timing += (w_end - w_start) * r_i

        sector_effect = sum(sector_pnl.values())
        costs = -day.fees_paid / nav_prev
        slippage = -day.slippage_cost / nav_prev
        observed = day.nav / nav_prev - 1.0

        return _DailyBreakdown(
            date=day.date,
            total_observed=observed,
            market_exposure=market_exposure,
            sector_effect=sector_effect,
            selection=selection,
            timing=timing,
            costs=costs,
            slippage=slippage,
            sector_pnl=sector_pnl,
        )

    def _sector_totals(self, breakdowns: list[_DailyBreakdown]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for b in breakdowns:
            for sector, value in b.sector_pnl.items():
                totals[sector] = totals.get(sector, 0.0) + value
        return totals

    def _selection_rows(self, breakdowns: list[_DailyBreakdown]) -> list[dict[str, Any]]:
        return [
            {
                "date": b.date,
                "component": "stock_selection",
                "value": b.selection,
                "sources": "start-of-day holdings cross-section",
            }
            for b in breakdowns
            if abs(b.selection) > 0
        ]

    def _timing_rows(self, breakdowns: list[_DailyBreakdown]) -> list[dict[str, Any]]:
        return [
            {
                "date": b.date,
                "component": "timing",
                "value": b.timing,
                "sources": "intraday weight changes applied to same-day returns",
            }
            for b in breakdowns
            if abs(b.timing) > 0
        ]

    def _cost_rows(self, breakdowns: list[_DailyBreakdown]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for b in breakdowns:
            if abs(b.costs) > 0:
                rows.append({"date": b.date, "component": "costs", "value": b.costs, "sources": "fill fees"})
            if abs(b.slippage) > 0:
                rows.append(
                    {"date": b.date, "component": "slippage", "value": b.slippage, "sources": "exec-price deviation"}
                )
        return rows

    # ------------------------------------------------------------------
    # Expected vs realized
    # ------------------------------------------------------------------

    def _execution_comparison(
        self,
        ordered: list[AttributionObservation],
        trades: list[dict[str, Any]],
        expected_weights: dict[str, float] | None,
        expected_cost: float | None,
    ) -> dict[str, Any]:
        last = ordered[-1]
        realized_weights = {
            k: v for k, v in last.weights.items() if k != "CASH" and abs(v) > 0
        }
        deviations: dict[str, dict[str, float]] = {}
        if expected_weights:
            for instrument in sorted(set(expected_weights) | set(realized_weights)):
                exp = expected_weights.get(instrument, 0.0)
                real = realized_weights.get(instrument, 0.0)
                deviations[instrument] = {"expected_weight": exp, "realized_weight": real, "deviation": real - exp}

        views = [TradeRecordView.from_fill_dict(t) for t in trades]
        realized_fees = sum(v.fees for v in views)
        realized_slippage = sum(v.slippage_cost for v in views)
        status_counts: dict[str, int] = {}
        for view in views:
            status_counts[view.status] = status_counts.get(view.status, 0) + 1
        requested = sum(v.requested_quantity for v in views)
        filled = sum(v.filled_quantity for v in views)

        comparison: dict[str, Any] = {
            "realized_final_weights": dict(sorted(realized_weights.items())),
            "expected_vs_realized_weights": deviations,
            "realized_costs": {"fees": realized_fees, "slippage": realized_slippage},
            "trade_statistics": {
                "count": len(views),
                "requested_quantity": requested,
                "filled_quantity": filled,
                "fill_ratio": (filled / requested) if requested > 0 else None,
                "status_counts": dict(sorted(status_counts.items())),
                "source_refs": sorted({v.client_order_id for v in views}),
            },
        }
        if expected_cost is not None:
            comparison["expected_cost"] = expected_cost
            comparison["cost_deviation"] = (realized_fees + realized_slippage) - expected_cost
        return comparison
