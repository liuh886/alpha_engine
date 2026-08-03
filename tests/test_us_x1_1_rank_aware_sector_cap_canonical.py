from __future__ import annotations

from scripts.run_us_x1_1_rank_aware_sector_cap_canonical import (
    canonical_relative_excess,
    canonicalize_aggregates,
)


def test_canonical_relative_excess_is_nav_ratio_not_return_difference() -> None:
    strategy_return = 2.311092
    benchmark_return = 0.551983
    result = canonical_relative_excess(strategy_return, benchmark_return)
    expected = (1 + strategy_return) / (1 + benchmark_return) - 1
    assert abs(result - expected) < 1e-12
    assert abs(result - (strategy_return - benchmark_return)) > 0.10


def test_canonicalize_aggregates_preserves_other_fields() -> None:
    rows = [
        {
            "strategy_id": "baseline_top15_equal",
            "cost_bps": 20,
            "compounded_total_return": 2.0,
            "compounded_benchmark_return": 0.5,
            "compounded_relative_excess": 1.5,
            "total_turnover": 10.0,
        }
    ]
    result = canonicalize_aggregates(rows)
    assert result[0]["compounded_relative_excess"] == 1.0
    assert result[0]["total_turnover"] == 10.0
    assert (
        result[0]["relative_excess_definition"]
        == "strategy_nav_divided_by_benchmark_nav_minus_1"
    )
    assert rows[0]["compounded_relative_excess"] == 1.5
