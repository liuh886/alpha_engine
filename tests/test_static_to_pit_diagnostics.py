"""Pure diagnostic tests for static-to-PIT decomposition."""

from __future__ import annotations

import pandas as pd
import pytest

from src.research.static_to_pit_decomposition import (
    contribution_gap,
    four_cell_effects,
    label_bin_migration,
    score_rank_migration,
    selected_return_contributions,
    selection_overlap,
    symbol_membership_categories,
    topk_selections,
)


def _frame(values: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    instruments = list(values)
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(dates), instruments], names=["datetime", "instrument"]
    )
    ordered = [
        values[symbol][date_index]
        for date_index in range(len(dates))
        for symbol in instruments
    ]
    return pd.DataFrame({"score": ordered}, index=index)


def _returns(values: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    frame = _frame(values, dates).rename(columns={"score": "return"})
    frame.attrs.update({"provenance": "raw_forward_return", "horizon": 10})
    return frame


def test_topk_overlap_and_rank_migration() -> None:
    dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
    left = _frame({"A": [3, 2, 1], "B": [2, 3, 2], "C": [1, 1, 3]}, dates)
    right = _frame({"A": [1, 2, 1], "B": [3, 1, 2], "C": [2, 3, 3]}, dates)
    left_sel = topk_selections(left, top_n=2, rebalance_days=2)
    right_sel = topk_selections(right, top_n=2, rebalance_days=2)
    assert left_sel["2025-01-02"] == ["A", "B"]
    overlap = selection_overlap(left_sel, right_sel)
    assert overlap[0]["intersection_count"] == 1
    migration = score_rank_migration(left, right)
    assert migration["common_rows"] == 9
    assert migration["mean_absolute_percentile_shift"] > 0


def test_label_bin_migration_detects_peer_group_change() -> None:
    dates = ["2025-01-02", "2025-01-03"]
    static = _returns({"A": [0.3, 0.1], "B": [0.2, 0.2], "C": [0.1, 0.3]}, dates)
    pit = _returns({
        "A": [0.3, 0.1], "B": [0.2, 0.2], "C": [0.1, 0.3], "D": [0.4, 0.4]
    }, dates)
    result = label_bin_migration(static, pit, n_bins=5)
    assert result["common_rows"] == 6
    assert result["changed_ratio"] > 0


def test_symbol_categories_separate_future_entrants_and_exits() -> None:
    result = symbol_membership_categories(
        static_symbols=["COMMON", "FUTURE", "WATCH"],
        pit_symbols=["COMMON", "EXIT", "CURRENT"],
        latest_snapshot_symbols=["COMMON", "CURRENT", "FUTURE"],
        first_snapshot_by_symbol={"FUTURE": "2025-01-02"},
        window_snapshot_date="2024-01-02",
    )
    assert result["FUTURE"] == "static_only/future_entrant"
    assert result["EXIT"] == "pit_only/historical_exit"


def test_selected_return_contributions_reconcile() -> None:
    dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
    scores = _frame({"A": [3, 3, 3], "B": [2, 2, 2], "C": [1, 1, 1]}, dates)
    returns = _returns({"A": [0.1, 0.1, 0.2], "B": [0, 0, 0.1], "C": [-0.1, 0, 0]}, dates)
    result = selected_return_contributions(
        scores, returns, categories={"A": "common", "B": "static_only/future_entrant"},
        top_n=2, rebalance_days=2,
    )
    assert result["periods"][0]["gross_period_return"] == pytest.approx(0.05)
    assert result["periods"][1]["gross_period_return"] == pytest.approx(0.15)


def test_four_cell_effects_reconcile_interaction() -> None:
    result = four_cell_effects({
        "S/S": {"model": {"excess_return": 1.0}},
        "S/P": {"model": {"excess_return": 0.4}},
        "P/S": {"model": {"excess_return": 0.7}},
        "P/P": {"model": {"excess_return": -0.2}},
    })["model"]["excess_return"]
    assert result["oos_opportunity_set_effect"] == pytest.approx(-0.6)
    assert result["training_and_label_effect"] == pytest.approx(-0.3)
    assert result["interaction_residual"] == pytest.approx(-0.3)
    assert result["reconciled"] is True


def test_contribution_gap_reconciles() -> None:
    result = contribution_gap(
        {"by_symbol": {"A": 0.2, "B": 0.1}, "by_category": {"common": 0.2}},
        {"by_symbol": {"A": 0.05, "C": -0.1}, "by_category": {"common": 0.05}},
    )
    assert result["by_symbol"]["A"] == pytest.approx(0.15)
    assert result["by_symbol"]["C"] == pytest.approx(0.1)
