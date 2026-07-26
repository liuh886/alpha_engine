from __future__ import annotations

import pytest

from scripts.run_cn_residual_trend_evidence import aggregate_cn_reports


def _report(
    label: str,
    *,
    relative_excess: float = 0.05,
    drawdown: float = -0.10,
    spread: float = 0.02,
    positive_ratio: float = 1.0,
) -> dict:
    periods = [
        {
            "date": f"2024-01-{index + 2:02d}",
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
        for index in range(10)
    ]
    return {
        "window": {"label": label},
        "portfolio": {
            "total_return": 0.10,
            "benchmark_return": 0.05,
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
        "selection_tail_diagnostics": {
            "window_label": label,
            "periods": periods,
            "aggregate": {
                "mean_spread": spread,
                "positive_spread_ratio": positive_ratio,
            },
        },
    }


def test_cn_aggregate_can_support_only_all_predeclared_checks() -> None:
    reports = [
        _report("2024H1"),
        _report("2024H2"),
        _report("2025H1"),
        _report("2025H2"),
    ]

    aggregate = aggregate_cn_reports(reports)

    assert aggregate["hypothesis_supported_on_independent_market"] is True
    assert (
        aggregate["decision"]
        == "cn_residual_trend_quality_supported_for_future_validation"
    )
    assert aggregate["survivorship_bias"] is True
    assert aggregate["promotion_eligible"] is False
    assert aggregate["trade_ready"] is False


def test_cn_aggregate_rejects_economic_and_drawdown_failure() -> None:
    reports = [
        _report(
            "2024H1",
            relative_excess=-0.20,
            spread=-0.02,
            positive_ratio=0.20,
        ),
        _report(
            "2024H2",
            relative_excess=-0.10,
            drawdown=-0.25,
            spread=-0.02,
            positive_ratio=0.20,
        ),
        _report("2025H1", spread=-0.02, positive_ratio=0.20),
        _report("2025H2"),
    ]

    aggregate = aggregate_cn_reports(reports)

    assert aggregate["hypothesis_supported_on_independent_market"] is False
    assert aggregate["decision"] == "cn_residual_trend_quality_not_supported"
    assert "positive_excess_windows" in aggregate["failed_checks"]
    assert "drawdown_floor" in aggregate["failed_checks"]
    assert "top15_period_consistency" in aggregate["failed_checks"]


def test_cn_aggregate_requires_four_unique_windows() -> None:
    with pytest.raises(ValueError, match="requires 4 windows"):
        aggregate_cn_reports([_report("2024H1")])

    reports = [
        _report("2024H1"),
        _report("2024H1"),
        _report("2025H1"),
        _report("2025H2"),
    ]
    with pytest.raises(ValueError, match="labels must be unique"):
        aggregate_cn_reports(reports)
