from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.run_us_x1_1_rank_aware_sector_cap import (
    _decision,
    _evaluate,
    _file_manifest,
    _replacement_impact,
    _select_names,
)


def _ranked() -> pd.DataFrame:
    rows = []
    sectors = (
        ["Technology"] * 8
        + ["Industrials"] * 5
        + ["Health Care"] * 5
        + ["Communication Services"] * 5
    )
    for index, sector in enumerate(sectors, start=1):
        rows.append(
            {
                "instrument": f"S{index:02d}",
                "score": float(100 - index),
                "rank": index,
                "sector": sector,
            }
        )
    return pd.DataFrame(rows)


def _sector_map() -> dict[str, str]:
    ranked = _ranked()
    return dict(zip(ranked["instrument"], ranked["sector"], strict=True))


def test_rank_aware_sector_cap_keeps_15_and_replaces_in_rank_order() -> None:
    ranked = _ranked()[["instrument", "score", "rank"]]
    selected, audit, replacements = _select_names(
        ranked,
        _sector_map(),
        sector_cap=True,
    )
    assert len(selected) == 15
    counts = pd.Series(selected).map(_sector_map()).value_counts()
    assert int(counts.max()) <= 4
    assert selected[:4] == ["S01", "S02", "S03", "S04"]
    assert "S05" not in selected
    assert list(replacements["out_instrument"]) == [
        "S05",
        "S06",
        "S07",
        "S08",
        "S13",
    ]
    assert list(replacements["in_instrument"]) == [
        "S16",
        "S17",
        "S19",
        "S20",
        "S21",
    ]
    assert (
        audit.loc[audit["instrument"] == "S05", "selection_reason"].iloc[0]
        == "sector_cap"
    )


def _scores() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=11)
    rows = []
    names = list(_sector_map())
    for date_index, date in enumerate(dates):
        order = names if date_index < 10 else list(reversed(names))
        for rank, name in enumerate(order, start=1):
            rows.append(
                {
                    "datetime": date,
                    "instrument": name,
                    "score": float(len(names) - rank),
                }
            )
    return pd.DataFrame(rows)


def test_evaluate_reconciles_and_sector_cap_is_respected() -> None:
    scores = _scores()
    dates = [
        pd.Timestamp(value)
        for value in sorted(scores["datetime"].unique())
    ][::10]
    returns = {
        dates[0]: {
            name: 0.01 * ((index % 5) - 1)
            for index, name in enumerate(_sector_map(), start=1)
        },
        dates[1]: {
            name: 0.005 * ((index % 7) - 2)
            for index, name in enumerate(_sector_map(), start=1)
        },
    }
    benchmark = {date: 0.01 for date in dates}
    result, periods, contributions, selections, replacements = _evaluate(
        scores,
        returns,
        benchmark,
        _sector_map(),
        cost_bps=20,
        sector_cap=True,
    )
    reconciled = contributions.groupby("period_index")["net_contribution"].sum()
    expected = periods.set_index("period_index")["net_return"]
    pd.testing.assert_series_equal(reconciled, expected, check_names=False)
    held = contributions.loc[contributions["target_weight"] > 0]
    counts = held.groupby(["period_index", "sector"]).size()
    assert int(counts.max()) <= 4
    assert (
        selections.loc[selections["challenger_selected"]]
        .groupby("period_index")
        .size()
        .eq(15)
        .all()
    )
    assert not replacements.empty
    assert result["n_periods"] == 2


def test_replacement_impact_compares_incoming_and_outgoing_names() -> None:
    replacements = pd.DataFrame(
        {
            "period_index": [0],
            "rebalance_date": pd.to_datetime(["2025-01-02"]),
            "replacement_index": [1],
            "out_instrument": ["OUT"],
            "out_rank": [5],
            "out_sector": ["Technology"],
            "out_reason": ["sector_cap"],
            "in_instrument": ["IN"],
            "in_rank": [18],
            "in_sector": ["Industrials"],
            "rank_displacement": [13],
        }
    )
    baseline = pd.DataFrame(
        {
            "period_index": [0],
            "instrument": ["OUT"],
            "gross_contribution": [-0.02],
            "net_contribution": [-0.021],
            "forward_10d_return": [-0.30],
        }
    )
    candidate = pd.DataFrame(
        {
            "period_index": [0],
            "instrument": ["IN"],
            "gross_contribution": [0.01],
            "net_contribution": [0.009],
            "forward_10d_return": [0.15],
        }
    )
    result = _replacement_impact(replacements, baseline, candidate)
    assert abs(float(result.iloc[0]["gross_return_impact"]) - 0.03) < 1e-12
    assert abs(float(result.iloc[0]["net_return_impact"]) - 0.03) < 1e-12


def test_decision_supports_shadow_only_when_all_gates_pass() -> None:
    aggregates = [
        {
            "strategy_id": "baseline_top15_equal",
            "cost_bps": 20,
            "compounded_relative_excess": 1.0,
            "worst_window_drawdown": -0.34,
            "total_turnover": 20.0,
            "strongest_positive_window_share": 0.40,
        },
        {
            "strategy_id": "top15_equal_rank_aware_sector_cap",
            "cost_bps": 20,
            "compounded_relative_excess": 0.95,
            "worst_window_drawdown": -0.29,
            "total_turnover": 22.0,
            "strongest_positive_window_share": 0.40,
        },
        {
            "strategy_id": "top15_equal_rank_aware_sector_cap",
            "cost_bps": 60,
            "compounded_relative_excess": 0.70,
            "worst_window_drawdown": -0.30,
            "total_turnover": 22.0,
            "strongest_positive_window_share": 0.40,
        },
    ]
    windows = [
        {
            "strategy_id": "top15_equal_rank_aware_sector_cap",
            "cost_bps": 20,
            "excess_return": 0.1,
        }
        for _ in range(4)
    ]
    result = _decision(aggregates, windows, deterministic=True)
    assert result["decision"] == "rank_aware_sector_cap_supported_for_shadow"
    assert result["shadow_eligible"] is True
    assert result["automatic_model_update"] is False


def test_file_manifest_is_stable(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")
    first = _file_manifest(tmp_path)
    second = _file_manifest(tmp_path)
    assert first == second
    assert set(first) == {"a.txt", "b.txt"}
