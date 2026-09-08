"""T47.5: Post-decision performance and execution attribution tests.

Verify:
- attribution reconciles to the observed portfolio return within tolerance
- every contribution references source dates/instruments/trades
- unexplained residual is reported explicitly
- expected versus realized weights, costs and fill statistics are compared
- results are stamped as advisory paper-simulation artifacts
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.portfolio.attribution import (
    AttributionError,
    AttributionObservation,
    AttributionReport,
    PaperPerformanceAttributor,
)


def obs(
    date,
    nav,
    weights,
    instrument_returns,
    benchmark_return=0.0,
    sector_returns=None,
    fees_paid=0.0,
    slippage_cost=0.0,
):
    return AttributionObservation(
        date=date,
        nav=nav,
        weights=dict(weights),
        instrument_returns=dict(instrument_returns),
        benchmark_return=benchmark_return,
        sector_returns=sector_returns,
        fees_paid=fees_paid,
        slippage_cost=slippage_cost,
    )


def attributor():
    return PaperPerformanceAttributor(tolerance=1e-9)


def fill(cid, instrument, side, date, requested, filled, status, fees=0.0, slip=0.0):
    return {
        "client_order_id": cid,
        "instrument": instrument,
        "side": side,
        "trade_date": date,
        "requested_quantity": requested,
        "filled_quantity": filled,
        "status": status,
        "fees": fees,
        "slippage_cost": slip,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_static_holdings_decompose_exactly_with_zero_residual() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.6, "BBB": 0.4}, {}),
        obs(
            "2026-08-25",
            101_000.0,
            {"AAA": 0.6, "BBB": 0.4},
            {"AAA": 0.02, "BBB": -0.005},
            benchmark_return=0.01,
        ),
    ]
    report = attributor().attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    total = sum(report.contributions.values()) + report.residual
    assert math.isclose(total, report.total_return_arithmetic, abs_tol=1e-12)
    assert report.reconciliation["within_tolerance"] is True
    assert abs(report.residual) <= 1e-12


def test_market_and_selection_components_hand_computed() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.5, "BBB": 0.5}, {}),
        obs(
            "2026-08-25",
            100_000.0 * (1 + 0.5 * 0.02 + 0.5 * -0.01),
            {"AAA": 0.5, "BBB": 0.5},
            {"AAA": 0.02, "BBB": -0.01},
            benchmark_return=0.005,
        ),
    ]
    report = attributor().attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    assert math.isclose(report.contributions["market_exposure"], 0.005, abs_tol=1e-12)
    assert math.isclose(report.contributions["stock_selection"], 0.0, abs_tol=1e-12)
    assert math.isclose(report.total_return_arithmetic, 0.005, abs_tol=1e-12)


def test_sector_effect_is_reported_per_sector_with_sources() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAPL": 0.6}, {}, ),
        obs(
            "2026-08-25",
            100_000.0 * (1 + 0.6 * 0.03),
            {"AAPL": 0.6},
            {"AAPL": 0.03},
            benchmark_return=0.01,
            sector_returns={"Tech": 0.02},
        ),
    ]
    report = attributor().attribute(
        observations=observations,
        model_version_id="mv",
        data_snapshot_id="snap",
        sector_of={"AAPL": "Tech"},
    )
    assert math.isclose(report.sector_contribution["Tech"], 0.6 * (0.02 - 0.01), abs_tol=1e-12)
    assert math.isclose(report.total_return_arithmetic, 0.018, abs_tol=1e-12)
    selection_row = report.selection_detail[0]
    assert selection_row["date"] == "2026-08-25"


def test_timing_captures_intraday_weight_changes() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.0}, {}),
        obs("2026-08-25", 100_000.0 * 1.001, {"AAA": 0.5}, {"AAA": 0.002}),
    ]
    report = attributor().attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    assert report.contributions["timing"] == pytest.approx(0.5 * 0.002, abs=1e-12)
    timing_rows = [row for row in report.timing_detail if row["date"] == "2026-08-25"]
    assert timing_rows


def test_costs_and_slippage_are_negative_contributions_with_dates() -> None:
    day = {
        "weights": {"AAA": 0.5},
        "instrument_returns": {"AAA": 0.01},
    }
    observations = [
        obs("2026-08-24", 100_000.0, day["weights"], {}),
        obs(
            "2026-08-25",
            100_000.0 * (1 + 0.005) - 30.0,
            day["weights"],
            day["instrument_returns"],
            fees_paid=20.0,
            slippage_cost=10.0,
        ),
    ]
    report = attributor().attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    assert report.contributions["costs"] == pytest.approx(-20.0 / 100_000.0, abs=1e-15)
    assert report.contributions["slippage"] == pytest.approx(-10.0 / 100_000.0, abs=1e-15)
    components = {row["component"]: row for row in report.cost_detail}
    assert components["costs"]["sources"] == "fill fees"
    assert components["slippage"]["sources"] == "exec-price deviation"


def test_inconsistent_inputs_surface_as_reported_residual_not_silent_match() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.5}, {}),
        obs("2026-08-25", 105_000.0, {"AAA": 0.5}, {"AAA": 0.001}),
    ]
    loose = PaperPerformanceAttributor(tolerance=1e-3)
    report = loose.attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    assert abs(report.residual) > 0
    assert report.reconciliation["within_tolerance"] is False
    assert "warning" in report.reconciliation


def test_multi_day_totals_sum_daily_contributions() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.5, "CASH": 0.5}, {}),
        obs("2026-08-25", 100_500.0, {"AAA": 0.5, "CASH": 0.5}, {"AAA": 0.01}),
        obs("2026-08-26", 101_000.0, {"AAA": 0.5, "CASH": 0.5}, {"AAA": 0.01}),
    ]
    report = attributor().attribute(
        observations=observations, model_version_id="mv", data_snapshot_id="snap"
    )
    assert report.attributed_days == 2
    expected_total = (100_500.0 / 100_000.0 - 1) + (101_000.0 / 100_500.0 - 1)
    assert math.isclose(report.total_return_arithmetic, expected_total, rel_tol=1e-12)
    assert report.window_start == "2026-08-25"
    assert report.window_end == "2026-08-26"


# ---------------------------------------------------------------------------
# Execution comparison
# ---------------------------------------------------------------------------


def test_expected_vs_realized_weights_and_costs_are_compared() -> None:
    trades = [
        fill("o1", "AAA", "buy", "2026-08-25", 100, 90, "partially_filled", fees=2.0, slip=1.5),
        fill("o2", "BBB", "buy", "2026-08-25", 50, 50, "filled", fees=1.0, slip=0.5),
    ]
    observations = [
        obs("2026-08-24", 100_000.0, {}, {}),
        obs("2026-08-25", 100_010.0, {"AAA": 0.45, "BBB": 0.55}, {}),
    ]
    report = attributor().attribute(
        observations=observations,
        trades=trades,
        expected_weights={"AAA": 0.5, "BBB": 0.5},
        expected_cost=2.0,
        model_version_id="mv",
        plan_id="plan_1",
        data_snapshot_id="snap",
    )
    comparison = report.execution_comparison
    deviation = comparison["expected_vs_realized_weights"]
    assert deviation["AAA"]["deviation"] == pytest.approx(-0.05, abs=1e-12)
    assert deviation["BBB"]["deviation"] == pytest.approx(0.05, abs=1e-12)
    assert comparison["expected_cost"] == 2.0
    assert comparison["cost_deviation"] == pytest.approx((3.0 + 2.0) - 2.0, abs=1e-12)
    stats = comparison["trade_statistics"]
    assert stats["count"] == 2
    assert stats["status_counts"] == {"filled": 1, "partially_filled": 1}
    assert stats["fill_ratio"] == pytest.approx(140 / 150, abs=1e-12)
    assert sorted(stats["source_refs"]) == ["o1", "o2"]
    assert report.plan_id == "plan_1"


def test_trade_records_missing_required_fields_fail_closed() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {}, {}),
        obs("2026-08-25", 100_000.0, {}, {}),
    ]
    with pytest.raises(AttributionError) as excinfo:
        attributor().attribute(
            observations=observations,
            trades=[{"client_order_id": "x"}],
            model_version_id="mv",
            data_snapshot_id="snap",
        )
    assert any("missing fields" in r for r in excinfo.value.reasons)


# ---------------------------------------------------------------------------
# Validation, identity and determinism
# ---------------------------------------------------------------------------


def test_identity_fields_and_minimum_observations_enforced() -> None:
    single = [obs("2026-08-24", 100_000.0, {}, {})]
    with pytest.raises(AttributionError):
        attributor().attribute(observations=single, model_version_id="mv", data_snapshot_id="snap")
    pair = single + [obs("2026-08-25", 101_000.0, {}, {})]
    with pytest.raises(AttributionError) as excinfo:
        attributor().attribute(observations=pair, model_version_id="", data_snapshot_id="snap")
    assert any("model_version_id" in r for r in excinfo.value.reasons)
    with pytest.raises(AttributionError) as excinfo:
        attributor().attribute(observations=pair, model_version_id="mv", data_snapshot_id="")
    assert any("data_snapshot_id" in r for r in excinfo.value.reasons)


def test_invalid_inputs_fail_closed() -> None:
    base = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.5}, {}),
        obs("2026-08-25", 101_000.0, {"AAA": 0.5}, {"AAA": 0.01}),
    ]
    with pytest.raises(AttributionError):
        attributor().attribute(
            observations=[
                base[0],
                obs("2026-08-25", float("nan"), {"AAA": 0.5}, {"AAA": 0.01}),
            ],
            model_version_id="mv",
            data_snapshot_id="snap",
        )
    with pytest.raises(AttributionError):
        attributor().attribute(
            observations=[
                base[0],
                obs("2026-08-25", 101_000.0, {"AAA": 1.5}, {"AAA": 0.01}),
            ],
            model_version_id="mv",
            data_snapshot_id="snap",
        )
    with pytest.raises(AttributionError):
        attributor().attribute(
            observations=[base[0], base[1], base[1]],
            model_version_id="mv",
            data_snapshot_id="snap",
        )


def test_invalid_tolerance_fails_closed() -> None:
    with pytest.raises(AttributionError):
        PaperPerformanceAttributor(tolerance=0.0)
    with pytest.raises(AttributionError):
        PaperPerformanceAttributor(tolerance=float("inf"))


def test_report_is_deterministic_and_stamped_advisory() -> None:
    observations = [
        obs("2026-08-24", 100_000.0, {"AAA": 0.6}, {}),
        obs("2026-08-25", 101_200.0, {"AAA": 0.6}, {"AAA": 0.02}, benchmark_return=0.01),
    ]
    kwargs = dict(model_version_id="mv", plan_id="p", data_snapshot_id="snap")
    first: AttributionReport = attributor().attribute(observations=observations, **kwargs)
    second: AttributionReport = attributor().attribute(observations=observations, **kwargs)
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["venue"] == "paper_simulation"
    assert payload["schema_version"] == "paper_attribution_v1"
