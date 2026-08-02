from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.audit_yahoo_adjustment_modes import (
    PRICE_COLUMNS,
    compare_frames,
    decide,
    derive_adjusted_ohlc,
)


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "adj_close": [5.25, 5.75, 6.25],
            "volume": [100.0, 110.0, 120.0],
        }
    )


def _adjusted_frame() -> pd.DataFrame:
    return derive_adjusted_ohlc(_raw_frame())


def _comparison(exact: bool = True) -> dict:
    return {
        "exact_match": exact,
        "material_match_1e_8": exact,
        "row_calendar_match": True,
    }


def _summary() -> dict:
    symbols = ["AAA", "BBB"]
    return {
        "mode_reproducibility": {
            "raw_no_repair": {
                symbol: {
                    **_comparison(True),
                    "raw_ohlcv_exact": True,
                    "adj_close_exact": True,
                }
                for symbol in symbols
            },
            "adjusted_no_repair": {
                symbol: _comparison(True) for symbol in symbols
            },
            "adjusted_repair": {
                symbol: _comparison(True) for symbol in symbols
            },
        },
        "derived_adjustment_comparison": {
            pass_id: {symbol: _comparison(True) for symbol in symbols}
            for pass_id in ("a", "b")
        },
    }


def test_derived_adjustment_scales_ohlc_and_preserves_volume() -> None:
    raw = _raw_frame()
    adjusted = derive_adjusted_ohlc(raw)
    assert list(adjusted.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    for column in PRICE_COLUMNS:
        expected = raw[column] * 0.5
        pd.testing.assert_series_equal(
            adjusted[column],
            expected,
            check_names=False,
        )
    pd.testing.assert_series_equal(
        adjusted["volume"],
        raw["volume"],
        check_names=False,
    )


def test_compare_frames_detects_material_adjusted_difference() -> None:
    left = _adjusted_frame()
    right = left.copy()
    right.loc[0, "close"] += 0.01
    result = compare_frames(left, right)
    assert result["exact_match"] is False
    assert result["material_match_1e_8"] is False
    assert result["material_changed_date_count_1e_8"] == 1
    assert result["first_material_changed_date"] == "2025-01-02"


def test_decision_raw_bar_nondeterminism_has_highest_priority() -> None:
    summary = _summary()
    summary["mode_reproducibility"]["raw_no_repair"]["AAA"][
        "raw_ohlcv_exact"
    ] = False
    assert decide(summary) == "upstream_raw_bar_nondeterminism"


def test_decision_adj_close_revision_precedes_auto_adjust() -> None:
    summary = _summary()
    summary["mode_reproducibility"]["raw_no_repair"]["AAA"][
        "adj_close_exact"
    ] = False
    summary["mode_reproducibility"]["adjusted_no_repair"]["AAA"][
        "exact_match"
    ] = False
    assert decide(summary) == "upstream_adjustment_revision"


def test_decision_auto_adjust_computation_when_raw_and_adj_are_stable() -> None:
    summary = _summary()
    summary["mode_reproducibility"]["adjusted_no_repair"]["AAA"][
        "exact_match"
    ] = False
    assert decide(summary) == "auto_adjust_computation_nondeterminism"


def test_decision_repair_induced_when_only_repair_mode_changes() -> None:
    summary = _summary()
    summary["mode_reproducibility"]["adjusted_repair"]["BBB"][
        "exact_match"
    ] = False
    assert decide(summary) == "repair_induced_nondeterminism"


def test_decision_bounded_subset_reproducible() -> None:
    assert decide(_summary()) == "bounded_subset_reproducible"


def test_decision_mixed_when_derived_adjustment_differs() -> None:
    summary = _summary()
    summary["derived_adjustment_comparison"]["b"]["BBB"][
        "exact_match"
    ] = False
    assert decide(summary) == "mixed_or_unexplained_source_nondeterminism"
