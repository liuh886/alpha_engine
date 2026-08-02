from __future__ import annotations

import pandas as pd

from scripts.run_us_x1_1_qqq_trend_overlay import (
    WINDOWS,
    _aggregate,
    _candidate_gate,
    _compare_selection_identity,
    _decision,
    _selection_ledger,
    _state_evidence,
)


def test_selection_ledger_uses_daily_fixed_top15() -> None:
    dates = pd.bdate_range("2024-01-02", periods=11)
    rows = []
    for date_index, date in enumerate(dates):
        for name_index in range(20):
            rows.append(
                {
                    "datetime": date,
                    "instrument": f"S{name_index:02d}",
                    "score": float(100 - name_index + date_index / 100),
                }
            )
    ledger = _selection_ledger(pd.DataFrame(rows))
    assert len(ledger) == 165
    assert ledger["datetime"].nunique() == 11
    assert ledger.groupby("datetime")["target_weight"].sum().round(12).eq(1.0).all()
    assert ledger.groupby("datetime")["rank"].max().eq(15).all()


def test_selection_identity_accepts_csv_weight_roundtrip() -> None:
    observed = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-02"]),
            "instrument": ["AAA"],
            "score": [0.25],
            "rank": [1],
            "target_weight": [1.0 / 15.0],
        }
    )
    expected = observed.copy()
    expected["target_weight"] = 0.0666666666666666
    _compare_selection_identity(observed, expected)


def test_state_evidence_counts_reduced_risk_and_rebound_upside() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-16", "2025-01-30"])
    baseline = pd.DataFrame(
        {
            "rebalance_date": dates,
            "gross_exposure": [1.0, 1.0, 1.0],
            "net_return": [0.10, 0.08, -0.05],
            "benchmark_return": [0.02, 0.03, -0.02],
            "excess_return": [0.08, 0.05, -0.03],
            "qqq_trend_state": ["non_negative", "negative", "negative"],
        }
    )
    overlay = baseline.copy()
    overlay["gross_exposure"] = [1.0, 0.5, 0.5]
    overlay["net_return"] = [0.10, 0.04, -0.025]
    overlay["excess_return"] = overlay["net_return"] - overlay["benchmark_return"]
    result = _state_evidence(overlay, baseline)
    assert result["reduced_risk_rebalances"] == 2
    assert abs(result["reduced_risk_share"] - 2 / 3) < 1e-12
    assert abs(result["average_gross_exposure"] - 2 / 3) < 1e-12
    assert result["negative_trend_rebound_periods"] == 1
    assert abs(result["upside_forgone_on_negative_trend_rebounds"] - 0.04) < 1e-12


def _window_row(
    *,
    total: float,
    benchmark: float,
    drawdown: float,
    gross: float = 1.0,
) -> dict[str, object]:
    return {
        "total_return": total,
        "benchmark_return": benchmark,
        "excess_return": total - benchmark,
        "max_drawdown": drawdown,
        "n_periods": 12,
        "state_evidence": {"average_gross_exposure": gross},
    }


def test_aggregate_uses_compounded_relative_excess() -> None:
    rows = [
        _window_row(total=0.20, benchmark=0.10, drawdown=-0.10),
        _window_row(total=0.30, benchmark=0.05, drawdown=-0.20),
    ]
    result = _aggregate("test", 20, rows)
    expected_strategy = 1.2 * 1.3 - 1.0
    expected_benchmark = 1.1 * 1.05 - 1.0
    expected_relative = (1.0 + expected_strategy) / (1.0 + expected_benchmark) - 1.0
    assert abs(result["compounded_strategy_return"] - expected_strategy) < 1e-12
    assert abs(result["compounded_relative_excess_return"] - expected_relative) < 1e-12
    assert result["worst_drawdown"] == -0.20


def _gate_fixture(
    candidate_id: str,
    *,
    relative20: float,
    relative60: float,
    worst_drawdown: float,
    window_drawdowns: list[float],
    window_excess: list[float],
) -> tuple[
    dict[str, dict[str, dict[str, object]]],
    dict[str, dict[str, dict[str, object]]],
]:
    aggregates: dict[str, dict[str, dict[str, object]]] = {
        "baseline_100pct": {
            "20": {
                "compounded_relative_excess_return": 1.0,
                "worst_drawdown": -0.34,
            },
            "60": {"compounded_relative_excess_return": 0.8},
        },
        candidate_id: {
            "20": {
                "compounded_relative_excess_return": relative20,
                "worst_drawdown": worst_drawdown,
            },
            "60": {"compounded_relative_excess_return": relative60},
        },
    }
    windows: dict[str, dict[str, dict[str, object]]] = {}
    for index, window in enumerate(WINDOWS):
        windows[window] = {
            "baseline_100pct": {
                "20": {"max_drawdown": -0.20, "excess_return": 0.10}
            },
            candidate_id: {
                "20": {
                    "max_drawdown": window_drawdowns[index],
                    "excess_return": window_excess[index],
                }
            },
        }
    return aggregates, windows


def test_candidate_gate_supports_broad_50pct_overlay() -> None:
    aggregates, windows = _gate_fixture(
        "qqq_trend_50pct",
        relative20=0.95,
        relative60=0.60,
        worst_drawdown=-0.28,
        window_drawdowns=[-0.18, -0.185, -0.17, -0.19],
        window_excess=[0.09, 0.08, 0.12, 0.07],
    )
    gate = _candidate_gate("qqq_trend_50pct", aggregates, windows)
    assert gate["supported"] is True
    assert len(gate["benefit_windows"]) == 4


def test_decision_prefers_50pct_when_both_pass() -> None:
    gates = [
        {
            "strategy_id": "qqq_trend_50pct",
            "supported": True,
            "benefit_windows": ["2024H1", "2025H1"],
            "worst_drawdown_improvement": 0.05,
            "gates": {
                "retained_relative_excess_gate": True,
                "no_new_negative_window_gate": True,
            },
        },
        {
            "strategy_id": "qqq_trend_cash",
            "supported": True,
            "benefit_windows": ["2024H1", "2025H1"],
            "worst_drawdown_improvement": 0.08,
            "gates": {
                "retained_relative_excess_gate": True,
                "no_new_negative_window_gate": True,
            },
        },
    ]
    result = _decision(gates)
    assert result["decision"] == "qqq_trend_50pct_portfolio_candidate_supported"
    assert result["selected_portfolio_contract"] == "qqq_trend_50pct"


def test_decision_reports_upside_destruction() -> None:
    gates = [
        {
            "strategy_id": "qqq_trend_50pct",
            "supported": False,
            "benefit_windows": ["2024H1", "2025H1"],
            "worst_drawdown_improvement": 0.05,
            "gates": {
                "retained_relative_excess_gate": False,
                "no_new_negative_window_gate": True,
            },
        },
        {
            "strategy_id": "qqq_trend_cash",
            "supported": False,
            "benefit_windows": ["2025H1"],
            "worst_drawdown_improvement": 0.06,
            "gates": {
                "retained_relative_excess_gate": False,
                "no_new_negative_window_gate": False,
            },
        },
    ]
    result = _decision(gates)
    assert result["decision"] == "trend_overlay_destroys_too_much_upside"
    assert result["selected_portfolio_contract"] is None
