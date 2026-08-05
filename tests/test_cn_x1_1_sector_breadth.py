from __future__ import annotations

import pandas as pd

from src.research.cn130_tail_factor_discovery import PortfolioVariant, choose_holdings
from src.research.cn_x1_1_sector_breadth import (
    SectorBreadthModelSpec,
    block_bootstrap_relative_excess,
    run_sector_breadth_portfolio,
)


def _day(date: str, window: str = "2023H1") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scores = {
        "A": [100.0, 99.0, 98.0, 10.0],
        "B": [97.0, 96.0, 95.0, 9.0],
        "C": [94.0, 93.0, 92.0, 8.0],
        "D": [91.0, 90.0, 89.0, 7.0],
        "E": [88.0, 20.0, 19.0, 18.0],
    }
    counter = 1
    for sector, sector_scores in scores.items():
        for score in sector_scores:
            rows.append(
                {
                    "window": window,
                    "datetime": pd.Timestamp(date),
                    "instrument": f"{counter:06d}",
                    "entity": f"Name {counter}",
                    "sector": sector,
                    "score": score,
                    "execution_forward_return": 0.01 + counter / 10000.0,
                }
            )
            counter += 1
    return rows


def test_fixed_spec_is_four_sector_equal_weight_model() -> None:
    spec = SectorBreadthModelSpec()

    assert spec.sectors == 4
    assert spec.names_per_sector == 1
    assert spec.rebalance_sessions == 10
    assert spec.cost_bps == 20
    assert spec.variant().variant_id == "sector_4x1"


def test_sector_breadth_selects_four_strongest_broad_sectors() -> None:
    day = pd.DataFrame(_day("2023-01-03"))
    variant = PortfolioVariant(
        "sector_4x1", "sector_hierarchical", sectors=4, names_per_sector=1
    )

    chosen = choose_holdings(day, variant)

    assert list(chosen["sector"]) == ["A", "B", "C", "D"]
    assert chosen.groupby("sector").size().eq(1).all()


def test_portfolio_respects_rebalance_interval_and_costs() -> None:
    rows: list[dict[str, object]] = []
    dates = pd.bdate_range("2023-01-03", periods=12)
    for date in dates:
        rows.extend(_day(date.strftime("%Y-%m-%d")))
    ledger = pd.DataFrame(rows)
    benchmark = pd.Series(0.005, index=dates)
    variant = SectorBreadthModelSpec().variant()

    summary, periods, holdings, windows = run_sector_breadth_portfolio(
        ledger,
        benchmark,
        variant,
        windows=("2023H1",),
        rebalance_sessions=5,
        cost_bps=20,
    )

    assert len(periods) == 3
    assert len(holdings) == 12
    assert summary["rebalance_count"] == 3
    assert summary["relative_excess"] > 0.0
    assert windows.iloc[0]["window"] == "2023H1"
    assert periods.iloc[0]["cost"] > 0.0


def test_block_bootstrap_is_deterministic() -> None:
    periods = pd.DataFrame(
        {"relative_log_return": [0.01, -0.005, 0.02, 0.003, -0.001, 0.008]}
    )

    first = block_bootstrap_relative_excess(periods, samples=200, block_size=2, seed=7)
    second = block_bootstrap_relative_excess(periods, samples=200, block_size=2, seed=7)

    assert first == second
    assert 0.0 <= first["probability_positive"] <= 1.0
    assert first["p05"] <= first["median"] <= first["p95"]
