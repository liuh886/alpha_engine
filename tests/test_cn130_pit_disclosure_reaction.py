from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from scripts.run_cn130_pit_disclosure_reaction import (
    ARCHITECTURES,
    COMPONENTS,
    attach_reaction,
    choose,
    disclosures,
    reaction_table,
)


def test_disclosures_keep_latest_periodic_event_per_available_date(tmp_path: Path) -> None:
    rows = [
        {
            "symbol": "1",
            "filing_type": "PERIODIC_REPORT",
            "available_at": "2023-04-01T16:00:00+00:00",
            "fiscal_period": "FY",
            "event_id": "a",
        },
        {
            "symbol": "1",
            "filing_type": "PERIODIC_REPORT",
            "available_at": "2023-04-01T16:00:00+00:00",
            "fiscal_period": "FY",
            "event_id": "b",
        },
        {
            "symbol": "1",
            "filing_type": "OTHER",
            "available_at": "2023-04-01T16:00:00+00:00",
            "fiscal_period": "FY",
            "event_id": "c",
        },
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = disclosures(path)

    assert result["symbol"].tolist() == ["000001"]
    assert result["event_id"].tolist() == ["b"]
    assert result.iloc[0]["available_date"] == pd.Timestamp("2023-04-02")


def test_reaction_table_starts_strictly_after_disclosure_and_waits_three_sessions() -> None:
    calendar = pd.bdate_range("2023-01-02", periods=30)
    stock_close = pd.Series(np.arange(100.0, 130.0), index=calendar)
    benchmark_close = pd.Series(np.arange(200.0, 230.0), index=calendar)
    stock_open = stock_close + 1.0
    benchmark_open = benchmark_close + 0.5
    amount = pd.Series(np.arange(1000.0, 1030.0), index=calendar)
    panel = SimpleNamespace(
        calendar=calendar,
        fields={
            "close": pd.DataFrame({"000001": stock_close, "000300": benchmark_close}),
            "open": pd.DataFrame({"000001": stock_open, "000300": benchmark_open}),
            "amount": pd.DataFrame({"000001": amount, "000300": amount * 2.0}),
        },
    )
    events = pd.DataFrame(
        {
            "symbol": ["000001"],
            "available_date": [calendar[20]],
            "fiscal_period": ["FY"],
        }
    )

    result = reaction_table(events, panel, ["000001"])

    assert len(result) == 1
    assert result.iloc[0]["reaction_start"] == calendar[21]
    assert result.iloc[0]["reaction_complete"] == calendar[23]
    assert result.iloc[0]["start_index"] == 21
    assert result.iloc[0]["complete_index"] == 23
    assert all(np.isfinite(result.iloc[0][component]) for component in COMPONENTS)


def _day() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument": ["A", "B", "C", "D"],
            "sector": ["s1", "s1", "s1", "s2"],
            "score": [4.0, 3.0, 2.0, 1.0],
            "execution_forward_return": [0.01, 0.02, -0.01, 0.0],
        }
    )


def test_attach_reaction_requires_completed_window() -> None:
    event = pd.DataFrame(
        {
            "symbol": ["A"],
            "start_index": [5],
            "complete_index": [7],
            "fiscal_period": ["FY"],
            **{component: [0.1] for component in COMPONENTS},
        }
    )
    calendar_index = {pd.Timestamp("2023-01-10"): 6, pd.Timestamp("2023-01-11"): 7}

    before, _ = attach_reaction(
        _day(), {"A": event}, calendar_index, pd.Timestamp("2023-01-10")
    )
    complete, _ = attach_reaction(
        _day(), {"A": event}, calendar_index, pd.Timestamp("2023-01-11")
    )

    assert pd.isna(before.loc[before["instrument"] == "A", "abnormal_gap_1"]).all()
    assert complete.loc[complete["instrument"] == "A", "abnormal_gap_1"].iloc[0] == 0.1
    assert complete.loc[complete["instrument"] == "A", "event_age_sessions"].iloc[0] == 2


def test_bounded_architectures_preserve_declared_selection_rules() -> None:
    day = pd.DataFrame(
        {
            "instrument": ["A", "B", "C"],
            "sector": ["s1", "s1", "s1"],
            "score": [3.0, 2.0, 1.0],
            "abnormal_gap_1": [-0.2, 0.3, 0.1],
        }
    )

    assert choose(day, ARCHITECTURES[0], "abnormal_gap_1")["instrument"].tolist() == ["A"]
    assert choose(day, ARCHITECTURES[1], "abnormal_gap_1")["instrument"].tolist() == ["B"]
    assert choose(day, ARCHITECTURES[2], "abnormal_gap_1")["instrument"].tolist() == ["B"]
    assert choose(day, ARCHITECTURES[3], "abnormal_gap_1").empty
