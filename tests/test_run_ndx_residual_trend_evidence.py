from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.run_ndx_residual_trend_evidence import (
    CANDIDATE_ID,
    aggregate_window_reports,
)


def _tail(spread: float, positive_ratio: float) -> dict[str, object]:
    return {
        "window_label": "",
        "periods": [
            {
                "date": "2024-01-02",
                "portfolio": {
                    "net_return": 0.01,
                    "relative_excess": 0.01,
                    "turnover": 1.0,
                    "cost": 0.002,
                },
                "top_minus_bottom_spread": spread,
                "selected_above_median_ratio": 1.0,
                "selected_positive_return_ratio": 1.0,
                "selected_holdings": [],
                "bottom_k_diagnostic_symbols": [],
            }
            for _ in range(10)
        ],
        "aggregate": {
            "mean_spread": spread,
            "positive_spread_ratio": positive_ratio,
        },
    }


def _report(
    label: str,
    *,
    total_return: float = 0.10,
    benchmark_return: float = 0.05,
    relative_excess: float = 0.05,
    drawdown: float = -0.10,
    spread: float = 0.02,
    positive_ratio: float = 1.0,
) -> dict[str, object]:
    tail = _tail(spread, positive_ratio)
    tail["window_label"] = label
    return {
        "partial_window": label.endswith("_partial"),
        "window": {"label": label},
        "portfolio": {
            "total_return": total_return,
            "benchmark_return": benchmark_return,
            "relative_excess_return": relative_excess,
            "sharpe_ratio": 1.0,
            "max_drawdown": drawdown,
        },
        "score_coverage": {"minimum_observed_ratio": 0.95},
        "score_diagnostics": {
            "ic_ir": 0.20,
            "rank_ic_ir": 0.20,
            "top_bottom_spread_mean": 0.01,
        },
        "selection_tail_diagnostics": tail,
        "risk_exposure_diagnostics": {
            "selected_minus_universe_beta": -0.10,
        },
        "source_candidate_reference": {
            "candidate": "frozen",
            "total_return": -0.20,
            "benchmark_return": 0.10,
            "relative_excess_return": -0.25,
            "sharpe_ratio": -1.0,
            "max_drawdown": -0.25,
            "icir": -0.10,
            "rank_icir": -0.10,
            "rebalance_top3_spread": -0.04,
            "positive_top3_spread_ratio": 0.30,
        },
    }


def _source_aggregate() -> dict[str, object]:
    return {
        "candidate_v2": {
            "compounded_total_return": -0.10,
            "compounded_benchmark_return": 0.50,
            "compounded_relative_excess_return": -0.40,
            "positive_excess_windows": 0,
            "mean_sharpe": -0.20,
            "worst_drawdown": -0.30,
        }
    }


def test_aggregate_supports_only_complete_cross_window_economics() -> None:
    reports = [
        _report("2024H1"),
        _report("2024H2"),
        _report("2025H1"),
        _report("2025H2"),
        _report("2026H1_partial"),
    ]

    aggregate = aggregate_window_reports(
        reports,
        source_aggregate=_source_aggregate(),
    )

    assert aggregate["candidate"] == CANDIDATE_ID
    assert aggregate["hypothesis_supported_for_fresh_validation"] is True
    assert (
        aggregate["decision"]
        == "residual_trend_quality_supported_for_fresh_validation"
    )
    assert aggregate["promotion_eligible"] is False
    assert aggregate["trade_ready"] is False


def test_partial_window_never_counts_as_complete_window() -> None:
    reports = [
        _report("2024H1"),
        _report("2024H2"),
        _report("2025H1"),
        _report("2026H1_partial"),
        _report("2026H2_partial"),
    ]

    with pytest.raises(ValueError, match="four full windows and one partial"):
        aggregate_window_reports(
            reports,
            source_aggregate=_source_aggregate(),
        )


def test_failed_drawdown_and_stress_checks_reject_hypothesis() -> None:
    reports = [
        _report("2024H1"),
        _report("2024H2"),
        _report("2025H1", drawdown=-0.25),
        _report("2025H2"),
        _report(
            "2026H1_partial",
            relative_excess=-0.30,
            drawdown=-0.30,
            spread=-0.05,
            positive_ratio=0.20,
        ),
    ]

    aggregate = aggregate_window_reports(
        reports,
        source_aggregate=_source_aggregate(),
    )

    assert aggregate["hypothesis_supported_for_fresh_validation"] is False
    assert aggregate["decision"] == "residual_trend_quality_not_supported"
    assert "complete_windows.drawdown_floor" in aggregate["failed_checks"]
    assert "partial_stress.positive_relative_excess" in aggregate["failed_checks"]
    assert (
        "partial_stress.drawdown_not_worse_than_frozen"
        in aggregate["failed_checks"]
    )


def test_aggregate_rejects_low_score_coverage_without_neutral_fill() -> None:
    reports = [
        _report("2024H1"),
        _report("2024H2"),
        _report("2025H1"),
        _report("2025H2"),
        _report("2026H1_partial"),
    ]
    reports[0] = deepcopy(reports[0])
    reports[0]["score_coverage"]["minimum_observed_ratio"] = 0.50

    aggregate = aggregate_window_reports(
        reports,
        source_aggregate=_source_aggregate(),
    )

    assert aggregate["hypothesis_supported_for_fresh_validation"] is False
    assert "complete_windows.score_coverage" in aggregate["failed_checks"]
