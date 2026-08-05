from __future__ import annotations

import pandas as pd

from scripts.data.build_cn130_pit_event_families import (
    CALIBRATION_HALF_YEARS,
    build_r0_top3_rows,
    eligibility,
    half_year,
    quarter_ends,
)


def test_quarter_ends_respect_bounds() -> None:
    assert quarter_ends("2022-06-30", "2023-04-01") == [
        "2022-06-30",
        "2022-09-30",
        "2022-12-31",
        "2023-03-31",
    ]


def test_half_year_labels() -> None:
    assert half_year("2023-06-30") == "2023H1"
    assert half_year("2023-07-01") == "2023H2"


def test_r0_top3_preserves_four_sector_breadth() -> None:
    rows = []
    for sector_index in range(5):
        for name_index in range(4):
            rows.append(
                {
                    "window": "2023H1",
                    "datetime": "2023-01-03",
                    "instrument": f"{sector_index}{name_index}".zfill(6),
                    "sector": f"S{sector_index}",
                    "score": 100 - sector_index * 10 - name_index,
                }
            )
    result = build_r0_top3_rows(pd.DataFrame(rows))

    assert result["sector"].nunique() == 4
    assert len(result) == 12
    assert result.groupby("sector").size().eq(3).all()


def test_eligibility_requires_every_calibration_half_year() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_family": "earnings_forecast",
                "half_year": window,
                "fixed_recent_top3_coverage": 0.20,
                "fixed_distinct_top3_events": 35,
                "fixed_max_sector_share": 0.40,
                "primary_reconciliation_ratio": 0.98,
                "first_session_mapping_ratio": 1.0,
                "event_driven_top3_events": 70,
                "event_driven_symbols": 25,
                "event_driven_sectors": 8,
                "announcement_timestamp_completeness": 1.0,
                "event_driven_max_stage_share": 0.60,
            }
            for window in CALIBRATION_HALF_YEARS
        ]
    )

    assert eligibility(frame)[:2] == (True, True)
    assert eligibility(frame.iloc[:-1])[:2] == (False, False)


def test_primary_reconciliation_is_a_hard_model_gate() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_family": "earnings_forecast",
                "half_year": window,
                "fixed_recent_top3_coverage": 0.20,
                "fixed_distinct_top3_events": 35,
                "fixed_max_sector_share": 0.40,
                "primary_reconciliation_ratio": 0.80,
                "first_session_mapping_ratio": 1.0,
                "event_driven_top3_events": 70,
                "event_driven_symbols": 25,
                "event_driven_sectors": 8,
                "announcement_timestamp_completeness": 1.0,
                "event_driven_max_stage_share": 0.60,
            }
            for window in CALIBRATION_HALF_YEARS
        ]
    )

    assert eligibility(frame)[:2] == (False, False)
