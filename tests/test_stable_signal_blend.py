from __future__ import annotations

import pandas as pd

from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.stable_signal_blend import (
    BlendWeight,
    build_blend_candidates,
    build_two_signal_blend,
    daily_cross_sectional_zscore,
    default_blend_weights,
    invert_score,
)


def _index() -> pd.MultiIndex:
    return pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )


def test_daily_cross_sectional_zscore_normalizes_each_date() -> None:
    score = pd.DataFrame({"score": [1.0, 2.0, 3.0, 2.0, 2.0, 2.0]}, index=_index())

    z = daily_cross_sectional_zscore(score)

    first_day = z.loc[pd.Timestamp("2025-01-01"), "score"]
    second_day = z.loc[pd.Timestamp("2025-01-02"), "score"]
    assert round(float(first_day.mean()), 8) == 0.0
    assert round(float(first_day.std(ddof=0)), 8) == 1.0
    assert second_day.tolist() == [0.0, 0.0, 0.0]
    assert z.attrs["transform"] == "daily_cross_sectional_zscore"


def test_invert_score_preserves_shape_and_metadata() -> None:
    score = pd.DataFrame({"score": [1.0, -2.0, 3.0, 4.0, -5.0, 6.0]}, index=_index())
    score.attrs["provenance"] = "factor_baseline"

    inverted = invert_score(score)

    assert inverted["score"].tolist() == [-1.0, 2.0, -3.0, -4.0, 5.0, -6.0]
    assert inverted.attrs["provenance"] == "factor_baseline"
    assert inverted.attrs["inverted"] is True


def test_build_two_signal_blend_records_weights() -> None:
    ranker = pd.DataFrame({"score": [1.0, 2.0, 3.0, 1.0, 3.0, 5.0]}, index=_index())
    momentum = pd.DataFrame({"score": [3.0, 2.0, 1.0, 5.0, 3.0, 1.0]}, index=_index())

    blend = build_two_signal_blend(
        ranker,
        momentum,
        weight=BlendWeight(ranker_weight=0.5, momentum_weight=0.5),
        invert_momentum=True,
    )

    assert list(blend.columns) == ["score"]
    assert len(blend) == 6
    assert blend.attrs["provenance"] == "stable_signal_blend"
    assert blend.attrs["ranker_weight"] == 0.5
    assert blend.attrs["momentum_weight"] == 0.5
    assert blend.attrs["momentum_inverted"] is True


def test_build_blend_candidates_names_weights_and_preserves_count() -> None:
    ranker = {"lgbm:daily_ranker:momentum:gain5": pd.DataFrame({"score": range(6)}, index=_index())}
    momentum = pd.DataFrame({"score": [6, 5, 4, 3, 2, 1]}, index=_index())

    candidates = build_blend_candidates(ranker, momentum, weights=default_blend_weights())

    assert list(candidates) == [
        "blend:ranker_momentum:momentum:gain5:ranker0.25_momentum0.75",
        "blend:ranker_momentum:momentum:gain5:ranker0.5_momentum0.5",
        "blend:ranker_momentum:momentum:gain5:ranker0.75_momentum0.25",
    ]
    assert all(frame.attrs["provenance"] == "stable_signal_blend" for frame in candidates.values())


def test_blend_candidates_map_to_factor_baseline_kind_in_10d_experiment() -> None:
    raw = pd.DataFrame({"return": [0.01, 0.02, 0.03, -0.01, 0.01, 0.04]}, index=_index())
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR
    blend = pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.0, 0.1, 0.4]}, index=_index())
    blend.attrs["provenance"] = "stable_signal_blend"
    config = ResearchSessionConfig(
        market="us",
        symbols=["A", "B", "C"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-02",
        topk=2,
    )

    payload = run_10d_experiment(
        config=config,
        candidates={"blend:ranker_momentum:momentum:gain5:ranker0.5_momentum0.5": blend},
        raw_returns=raw,
    )

    kinds = {candidate["candidate_kind"] for candidate in payload["comparison_report"]["candidates"]}
    assert kinds == {"factor_baseline"}
