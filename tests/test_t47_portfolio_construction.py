"""T47.3: Risk-constrained portfolio construction tests.

Verify:
- identical inputs produce identical plans (determinism, input-order independence)
- every excluded/capped signal carries an explicit reason
- infeasible constraints fail closed
- total weights, cash, turnover, exposure and cost reconcile
- research-only advisory boundary is stamped on every plan
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.portfolio.construction import (
    AdvisoryExecutionPlan,
    ConstructionConstraints,
    PortfolioConstructionError,
    PortfolioConstructor,
    PortfolioRiskState,
    QualifiedSignal,
)


def make_signals(count: int, sector_cycle: int = 0) -> list[QualifiedSignal]:
    return [
        QualifiedSignal(
            instrument=f"I{i:03d}",
            score=1.0 / (i + 1),
            sector=(f"S{i % sector_cycle}" if sector_cycle else None),
            price=10.0 + i,
            avg_daily_value=10_000_000.0,
        )
        for i in range(count)
    ]


def build(constraints: ConstructionConstraints | None = None, **kwargs) -> AdvisoryExecutionPlan:
    defaults: dict = {
        "asof_date": "2026-08-26",
        "signals": make_signals(30),
        "model_version_id": "mv_test",
        "data_snapshot_id": "snap_test",
    }
    defaults.update(kwargs)
    return PortfolioConstructor(constraints or ConstructionConstraints(max_positions=10)).build_plan(**defaults)


# ---------------------------------------------------------------------------
# Determinism and identity
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_plans() -> None:
    first = build()
    second = build()
    assert first.plan_id == second.plan_id
    assert first.to_dict() == second.to_dict()


def test_plan_identity_is_input_order_independent() -> None:
    ordered = build()
    shuffled = list(reversed(make_signals(30)))
    reordered = build(signals=shuffled)
    assert ordered.plan_id == reordered.plan_id
    assert ordered.target_weights == reordered.target_weights


def test_changed_inputs_change_plan_identity() -> None:
    baseline = build()
    tweaked = build(
        signals=make_signals(30)[:29] + [QualifiedSignal(instrument="I029", score=-1.0, price=39.0, avg_daily_value=10_000_000.0)]
    )
    assert baseline.plan_id != tweaked.plan_id


def test_identity_fields_are_required() -> None:
    for field in ("asof_date", "model_version_id", "data_snapshot_id"):
        kwargs = {
            "asof_date": "2026-08-26",
            "signals": make_signals(5),
            "model_version_id": "mv",
            "data_snapshot_id": "snap",
        }
        kwargs[field] = ""
        with pytest.raises(PortfolioConstructionError) as excinfo:
            PortfolioConstructor(ConstructionConstraints(max_positions=3)).build_plan(**kwargs)
        assert any(field.split("_")[0] in reason for reason in excinfo.value.reasons)


def test_plan_stamps_research_advisory_boundary() -> None:
    payload = build().to_dict()
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["advisory_only"] is True
    assert payload["schema_version"] == "portfolio_construction_advisory_v1"


# ---------------------------------------------------------------------------
# Selection reasons
# ---------------------------------------------------------------------------


def test_every_signal_receives_exactly_one_reasoned_decision() -> None:
    plan = build()
    by_code: dict[str, list[str]] = {}
    for decision in plan.decisions:
        by_code.setdefault(decision.reason_code, []).append(decision.instrument)
    assert len(plan.decisions) == 30
    assert len(by_code["selected"]) == 10
    assert len(by_code["rank_beyond_capacity"]) == 20
    assert {d.instrument for d in plan.decisions if d.status == "selected"} == set(plan.target_weights)


def test_sector_cap_limits_names_per_sector_with_reasons() -> None:
    constraints = ConstructionConstraints(
        max_positions=10, max_position_weight=0.2, max_names_per_sector=2
    )
    signals = make_signals(12, sector_cycle=3)
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
    )
    sector_of = {s.instrument: s.sector for s in signals}
    counts: dict[str, int] = {}
    for instrument in plan.target_weights:
        counts[sector_of[instrument]] = counts.get(sector_of[instrument], 0) + 1
    assert all(count <= 2 for count in counts.values())
    capped = [d for d in plan.decisions if d.reason_code == "capped_sector_name_limit"]
    assert capped
    for decision in capped:
        assert decision.status == "capped" and decision.weight is None
        assert "already holds" in decision.detail


def test_liquidity_floor_excludes_with_reason() -> None:
    constraints = ConstructionConstraints(
        max_positions=5, max_position_weight=1.0, min_avg_daily_value=5_000_000.0
    )
    signals = [
        QualifiedSignal(instrument="LIQ", score=2.0, price=10.0, avg_daily_value=1_000_000.0),
        QualifiedSignal(instrument="OKAY", score=1.0, price=10.0, avg_daily_value=9_000_000.0),
    ]
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
    )
    assert "LIQ" not in plan.target_weights
    decision = next(d for d in plan.decisions if d.instrument == "LIQ")
    assert decision.reason_code == "excluded_liquidity_floor"
    assert "below floor" in decision.detail


def test_untradable_or_unpriced_instruments_are_excluded() -> None:
    signals = [
        QualifiedSignal(instrument="HALT", score=3.0, price=10.0, tradable=False),
        QualifiedSignal(instrument="NOPX", score=2.5, price=None),
        QualifiedSignal(instrument="ZERO", score=2.0, price=0.0),
        QualifiedSignal(instrument="GOOD", score=1.0, price=5.0),
    ]
    plan = PortfolioConstructor(ConstructionConstraints(max_positions=4, max_position_weight=1.0)).build_plan(
        asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
    )
    assert set(plan.target_weights) == {"GOOD"}
    codes = {d.instrument: d.reason_code for d in plan.decisions}
    assert codes["HALT"] == codes["NOPX"] == codes["ZERO"] == "excluded_not_tradable"


def test_equal_scores_break_ties_by_instrument_ascending() -> None:
    signals = [QualifiedSignal(instrument=name, score=1.0, price=10.0) for name in ["C", "A", "B"]]
    plan = PortfolioConstructor(ConstructionConstraints(max_positions=2, max_position_weight=0.5)).build_plan(
        asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
    )
    assert set(plan.target_weights) == {"A", "B"}
    dropped = next(d for d in plan.decisions if d.reason_code == "rank_beyond_capacity")
    assert dropped.instrument == "C"


# ---------------------------------------------------------------------------
# Sizing, risk state and reconciliation
# ---------------------------------------------------------------------------


def test_cash_target_and_gross_exposure_reconcile() -> None:
    constraints = ConstructionConstraints(max_positions=8, target_cash_weight=0.05, max_position_weight=0.2)
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26", signals=make_signals(20), model_version_id="mv", data_snapshot_id="snap"
    )
    assert math.isclose(sum(plan.target_weights.values()), 0.95, abs_tol=1e-9)
    assert math.isclose(plan.cash_weight, 0.05, abs_tol=1e-9)
    assert math.isclose(plan.gross_exposure, 0.95, abs_tol=1e-9)
    assert all(value for value in plan.reconciliation.values())


def test_drawdown_deleverage_triggers_at_threshold_with_warning() -> None:
    constraints = ConstructionConstraints(
        max_positions=4,
        max_position_weight=0.3,
        drawdown_deleverage_threshold=-0.20,
        deleveraged_gross_exposure=0.60,
    )
    constructor = PortfolioConstructor(constraints)

    calm = constructor.build_plan(
        asof_date="2026-08-26",
        signals=make_signals(6),
        risk_state=PortfolioRiskState(current_drawdown=-0.19),
        model_version_id="mv",
        data_snapshot_id="snap",
    )
    stressed = constructor.build_plan(
        asof_date="2026-08-26",
        signals=make_signals(6),
        risk_state=PortfolioRiskState(current_drawdown=-0.25),
        model_version_id="mv",
        data_snapshot_id="snap",
    )
    assert math.isclose(calm.gross_exposure, 1.0, abs_tol=1e-9)
    assert not calm.warnings
    assert math.isclose(stressed.gross_exposure, 0.60, abs_tol=1e-9)
    assert any("gross exposure reduced" in w for w in stressed.warnings)


def test_risk_limit_breach_flag_deleverages_even_above_threshold() -> None:
    constraints = ConstructionConstraints(
        max_positions=4,
        max_position_weight=0.3,
        drawdown_deleverage_threshold=-0.50,
        deleveraged_gross_exposure=0.50,
    )
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26",
        signals=make_signals(6),
        risk_state=PortfolioRiskState(current_drawdown=-0.05, risk_limit_breached=True),
        model_version_id="mv",
        data_snapshot_id="snap",
    )
    assert math.isclose(plan.gross_exposure, 0.50, abs_tol=1e-9)


def test_turnover_matches_brute_force_and_cost_formula() -> None:
    current = {f"I{i:03d}": 0.10 for i in range(5)}
    plan = build(current_weights=current)
    universe = set(plan.target_weights) | set(current)
    brute = sum(abs(plan.target_weights.get(i, 0.0) - current.get(i, 0.0)) for i in universe) / 2.0
    assert math.isclose(plan.one_sided_turnover, brute, abs_tol=1e-9)
    expected_cost = plan.traded_notional_fraction * 20.0 / 10_000.0
    assert math.isclose(plan.expected_transaction_cost, expected_cost, abs_tol=1e-12)


def test_turnover_budget_removes_lowest_conviction_new_names() -> None:
    current = {f"I{i:03d}": 0.125 for i in range(4, 12)}
    constraints = ConstructionConstraints(
        max_positions=8, max_position_weight=0.20, max_turnover=0.35
    )
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26",
        signals=make_signals(12),
        current_weights=current,
        model_version_id="mv",
        data_snapshot_id="snap",
    )
    kept_new = set(plan.target_weights) - set(current)
    trimmed = [d for d in plan.decisions if d.reason_code == "removed_turnover_budget"]
    assert trimmed
    assert all(d.status == "removed" and d.weight is None for d in trimmed)
    for name in (d.instrument for d in trimmed):
        assert name not in plan.target_weights
        assert name not in current
    scores = {s.instrument: s.score for s in make_signals(12)}
    if kept_new and trimmed:
        weakest_kept = min(scores[n] for n in kept_new)
        strongest_trimmed = max(scores[d.instrument] for d in trimmed)
        assert strongest_trimmed <= weakest_kept


def test_forced_exit_alone_over_budget_fails_closed() -> None:
    current = {f"GONE{i}": 0.20 for i in range(5)}
    with pytest.raises(PortfolioConstructionError) as excinfo:
        PortfolioConstructor(
            ConstructionConstraints(max_positions=5, max_position_weight=0.25, max_turnover=0.01)
        ).build_plan(
            asof_date="2026-08-26",
            signals=make_signals(10),
            current_weights=current,
            model_version_id="mv",
            data_snapshot_id="snap",
        )
    assert any("forced exits alone" in reason for reason in excinfo.value.reasons)


def test_equal_weight_above_position_cap_fails_closed() -> None:
    constraints = ConstructionConstraints(max_positions=10, max_position_weight=0.10)
    signals = make_signals(5)
    with pytest.raises(PortfolioConstructionError) as excinfo:
        PortfolioConstructor(constraints).build_plan(
            asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
        )
    assert any("exceeds" in reason and "max_position_weight" in reason for reason in excinfo.value.reasons)


def test_equal_weight_at_exact_position_cap_is_feasible() -> None:
    constraints = ConstructionConstraints(max_positions=5, max_position_weight=0.20)
    plan = PortfolioConstructor(constraints).build_plan(
        asof_date="2026-08-26", signals=make_signals(5), model_version_id="mv", data_snapshot_id="snap"
    )
    assert all(math.isclose(w, 0.20, abs_tol=1e-9) for w in plan.target_weights.values())
    assert all(plan.reconciliation.values())


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "constraints",
    [
        ConstructionConstraints(max_positions=0),
        ConstructionConstraints(target_cash_weight=1.0),
        ConstructionConstraints(target_cash_weight=-0.1),
        ConstructionConstraints(max_position_weight=0.0),
        ConstructionConstraints(max_names_per_sector=0),
        ConstructionConstraints(max_turnover=-0.5),
        ConstructionConstraints(min_avg_daily_value=-1.0),
        ConstructionConstraints(transaction_cost_bps=-1.0),
        ConstructionConstraints(weight_scheme="score"),
        ConstructionConstraints(drawdown_deleverage_threshold=-0.2),
        ConstructionConstraints(max_sector_weight=1.5),
    ],
)
def test_invalid_constraint_sets_fail_closed(constraints: ConstructionConstraints) -> None:
    with pytest.raises(PortfolioConstructionError):
        PortfolioConstructor(constraints)


def test_duplicate_instruments_fail_closed() -> None:
    dup = QualifiedSignal(instrument="DUP", score=1.0, price=10.0)
    with pytest.raises(PortfolioConstructionError) as excinfo:
        build(signals=[dup, dup])
    assert any("duplicate" in r for r in excinfo.value.reasons)


def test_non_finite_scores_fail_closed() -> None:
    signals = [
        QualifiedSignal(instrument="NAN", score=math.nan, price=10.0),
        QualifiedSignal(instrument="INF", score=math.inf, price=10.0),
        QualifiedSignal(instrument="OK", score=0.5, price=10.0),
    ]
    with pytest.raises(PortfolioConstructionError) as excinfo:
        build(signals=signals)
    assert any("non-finite" in r and "INF" in r for r in excinfo.value.reasons)


def test_missing_sector_with_sector_cap_fails_closed() -> None:
    signals = [
        QualifiedSignal(instrument="A", score=2.0, price=10.0, sector=None),
        QualifiedSignal(instrument="B", score=1.0, price=10.0, sector="S"),
    ]
    with pytest.raises(PortfolioConstructionError) as excinfo:
        PortfolioConstructor(ConstructionConstraints(max_positions=2, max_names_per_sector=1)).build_plan(
            asof_date="2026-08-26", signals=signals, model_version_id="mv", data_snapshot_id="snap"
        )
    assert any("sector classification required" in r for r in excinfo.value.reasons)


def test_empty_or_fully_excluded_universes_fail_closed() -> None:
    with pytest.raises(PortfolioConstructionError):
        build(signals=[])
    halted = [QualifiedSignal(instrument=f"H{i}", score=1.0 / (i + 1), price=None) for i in range(3)]
    with pytest.raises(PortfolioConstructionError) as excinfo:
        build(signals=halted)
    assert any("no eligible" in r for r in excinfo.value.reasons)
