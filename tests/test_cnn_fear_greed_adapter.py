from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.cnn_fear_greed import parse_cnn_fear_greed


def _payload(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"fear_and_greed_historical": {"data": rows}}


def test_parse_cnn_fear_greed_builds_sorted_daily_frame() -> None:
    payload = _payload(
        [
            {"x": 1612224000000, "y": 18.5, "rating": "extreme fear"},
            {"x": 1612137600000, "y": 21.0, "rating": "extreme fear"},
        ]
    )
    frame = parse_cnn_fear_greed(payload)

    assert list(frame["fear_greed_score"]) == [21.0, 18.5]
    assert frame.index.is_monotonic_increasing
    assert frame.index[0] == pd.Timestamp("2021-02-01")


def test_parse_rejects_missing_history() -> None:
    with pytest.raises(ValueError, match="missing historical data"):
        parse_cnn_fear_greed({"fear_and_greed_historical": {"data": []}})


def test_parse_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError, match="out of range"):
        parse_cnn_fear_greed(
            _payload([{"x": 1612137600000, "y": 101.0, "rating": "invalid"}])
        )


def test_parse_rejects_duplicate_dates() -> None:
    with pytest.raises(ValueError, match="duplicate dates"):
        parse_cnn_fear_greed(
            _payload(
                [
                    {"x": 1612137600000, "y": 20.0, "rating": "extreme fear"},
                    {"x": 1612137600000, "y": 19.0, "rating": "extreme fear"},
                ]
            )
        )
