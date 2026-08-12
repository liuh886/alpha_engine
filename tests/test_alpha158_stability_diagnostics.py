from __future__ import annotations

from src.research.alpha158_stability_diagnostics import _classification


def _row(values: dict[str, float], *, coverage: float = 1.0) -> dict:
    return {
        "recommended_orientation": "keep_score",
        "coverage_ratio": coverage,
        "window_metrics": [
            {"window": window, "mean_rank_ic": value}
            for window, value in values.items()
        ],
    }


def test_cross_window_stable_requires_all_four_positive_windows() -> None:
    result = _classification(
        _row(
            {
                "2024H1": 0.01,
                "2024H2": 0.02,
                "2025H1": 0.03,
                "2025H2": 0.01,
            }
        )
    )
    assert result["cross_window_stable"] is True
    assert result["repair_2024_candidate"] is True
    assert result["regime_sensitive"] is False


def test_orientation_is_applied_before_stability_classification() -> None:
    row = _row(
        {
            "2024H1": -0.01,
            "2024H2": -0.02,
            "2025H1": -0.03,
            "2025H2": -0.01,
        }
    )
    row["recommended_orientation"] = "invert_score"
    result = _classification(row)
    assert result["cross_window_stable"] is True


def test_regime_sensitive_is_distinct_from_stable() -> None:
    result = _classification(
        _row(
            {
                "2024H1": 0.02,
                "2024H2": 0.01,
                "2025H1": -0.01,
                "2025H2": -0.02,
            }
        )
    )
    assert result["cross_window_stable"] is False
    assert result["regime_sensitive"] is True


def test_coverage_threshold_is_fail_closed() -> None:
    result = _classification(
        _row(
            {
                "2024H1": 0.01,
                "2024H2": 0.02,
                "2025H1": 0.03,
                "2025H2": 0.01,
            },
            coverage=0.949,
        )
    )
    assert result["coverage_ok"] is False
    assert result["cross_window_stable"] is False
