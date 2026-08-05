from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.research.cn130_ranking_pipeline import label_rank_identity, turnover
from src.research.cn130_cross_sectional_ranking import (
    forward_returns,
    make_label,
    read_qlib_feature,
    transform_hierarchical_scores,
)


def _index() -> pd.MultiIndex:
    return pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-02", "2025-01-03"]), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )


def _classification() -> dict[str, dict[str, str]]:
    return {
        "A": {"entity": "A", "sector": "S1", "industry": "I1"},
        "B": {"entity": "B", "sector": "S1", "industry": "I2"},
        "C": {"entity": "C", "sector": "S2", "industry": "I3"},
        "D": {"entity": "D", "sector": "S2", "industry": "I4"},
    }


def test_read_qlib_feature_respects_start_offset(tmp_path: Path) -> None:
    path = tmp_path / "close.day.bin"
    np.asarray([2.0, 10.0, 11.0, 12.0], dtype="<f4").tofile(path)
    result = read_qlib_feature(path, 7)
    np.testing.assert_allclose(result[2:5], [10.0, 11.0, 12.0])
    assert np.isnan(result[:2]).all()
    assert np.isnan(result[5:]).all()


def test_benchmark_relative_label_is_cross_sectionally_rank_equivalent() -> None:
    index = _index()
    raw = pd.DataFrame({"return": [0.01, 0.04, -0.01, 0.02, 0.03, 0.0, 0.02, -0.02]}, index=index)
    benchmark = pd.Series([0.005, 0.007], index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
    baseline = make_label(raw, mode="raw", benchmark_returns=benchmark, classification=_classification())
    relative = make_label(raw, mode="benchmark_relative", benchmark_returns=benchmark, classification=_classification())
    identity = label_rank_identity(baseline, relative)
    assert identity["minimum_daily_rank_correlation"] == 1.0
    assert identity["gain_labels_exactly_equal"] is True


def test_sector_relative_label_has_zero_sector_median() -> None:
    index = _index()
    raw = pd.DataFrame({"return": [0.01, 0.05, -0.02, 0.02, 0.03, 0.01, 0.04, -0.04]}, index=index)
    benchmark = pd.Series(0.0, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
    result = make_label(raw, mode="sector_relative", benchmark_returns=benchmark, classification=_classification())
    frame = result.join(pd.DataFrame(
        {"sector": [_classification()[symbol]["sector"] for symbol in index.get_level_values("instrument")]},
        index=index,
    ))
    medians = frame.groupby([frame.index.get_level_values("datetime"), "sector"])["target_return"].median()
    np.testing.assert_allclose(medians.to_numpy(), 0.0, atol=1e-15)


def test_hierarchical_score_uses_frozen_35_65_weights() -> None:
    date = pd.Timestamp("2025-01-02")
    security_index = pd.MultiIndex.from_product([[date], ["A", "B", "C", "D"]], names=["datetime", "instrument"])
    sector_index = pd.MultiIndex.from_tuples([(date, "S1"), (date, "S2")], names=["datetime", "instrument"])
    sector_scores = pd.DataFrame({"score": [0.0, 1.0]}, index=sector_index)
    security_scores = pd.DataFrame({"score": [0.0, 1.0, 0.0, 1.0]}, index=security_index)
    result = transform_hierarchical_scores(sector_scores, security_scores, classification=_classification())
    assert np.isclose(result.loc[(date, "A"), "score"], 0.35 * 0.5 + 0.65 * 0.5)
    assert np.isclose(result.loc[(date, "D"), "score"], 0.35 * 1.0 + 0.65 * 1.0)


def test_forward_returns_support_next_session_execution() -> None:
    dates = pd.date_range("2025-01-01", periods=13, freq="D")
    close = pd.DataFrame({"A": np.arange(1.0, 14.0)}, index=dates)
    same_close = forward_returns(close, horizon=10, delay=0)
    next_close = forward_returns(close, horizon=10, delay=1)
    assert np.isclose(same_close.iloc[0, 0], 11.0 / 1.0 - 1.0)
    assert np.isclose(next_close.iloc[0, 0], 12.0 / 2.0 - 1.0)



def test_cash_inclusive_turnover() -> None:
    assert np.isclose(turnover({}, {"A": 1.0}), 1.0)
    assert np.isclose(turnover({"A": 1.0}, {"A": 0.5}), 0.5)
