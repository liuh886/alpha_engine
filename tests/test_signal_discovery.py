"""Focused tests for the canonical fixed-10D signal discovery module."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.signal_discovery import (
    CandidateKind,
    CandidateStatus,
    DirectionRecommendation,
    ScoreOrientation,
    compute_direction_diagnostics,
    evaluate_candidate,
    generate_winner_labels,
    run_signal_discovery_comparison,
)


def _make_raw_returns(
    n_dates: int = 30,
    n_stocks: int = 40,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n_dates)
    instruments = [f"S{i:04d}" for i in range(n_stocks)]
    index = pd.MultiIndex.from_product(
        [dates, instruments],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame(
        {"return": rng.normal(0.001, 0.02, size=len(index))},
        index=index,
    )
    frame.attrs.update(
        provenance="raw_forward_return",
        label_expression="Ref($close, -10) / $close - 1",
        horizon=10,
    )
    return frame


def _make_predictions(raw_returns: pd.DataFrame, strength: float = 0.5) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    scores = raw_returns["return"] * strength + rng.normal(
        0,
        0.01,
        size=len(raw_returns),
    )
    return pd.DataFrame({"score": scores.to_numpy()}, index=raw_returns.index)


def _make_factor(raw_returns: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(21)
    return pd.DataFrame(
        {"score": rng.normal(0.0, 0.03, size=len(raw_returns))},
        index=raw_returns.index,
    )


def test_winner_labels_are_training_targets_only_and_need_raw_returns() -> None:
    raw = _make_raw_returns(n_dates=5, n_stocks=20)
    labels = generate_winner_labels(raw, top_fraction=0.2)
    assert "winner_label" in labels.columns
    assert set(labels["winner_label"].unique()).issubset({0, 1})

    processed = raw.copy()
    processed.attrs["provenance"] = "processed_training_label"
    with pytest.raises(ValueError, match="raw_forward_return"):
        generate_winner_labels(processed)


def test_evaluate_candidate_rejects_same_row_winner_labels_as_scores() -> None:
    raw = _make_raw_returns(n_dates=10, n_stocks=30)
    winner_labels = generate_winner_labels(raw, top_fraction=0.2)
    leaked_scores = winner_labels[["winner_label"]].rename(
        columns={"winner_label": "score"}
    )

    with pytest.raises(ValueError, match="out-of-sample winner predictions"):
        evaluate_candidate(
            predictions=leaked_scores,
            raw_returns=raw,
            candidate_kind=CandidateKind.WINNER_BUCKET_CLASSIFIER,
        )


def test_direction_recommendation_describes_current_orientation() -> None:
    raw = _make_raw_returns(n_dates=20, n_stocks=50)
    positive = _make_predictions(raw, strength=0.8)

    original = evaluate_candidate(
        predictions=positive,
        raw_returns=raw,
        candidate_kind=CandidateKind.LGBM_REGRESSOR,
        orientation=ScoreOrientation.ORIGINAL,
        topk=5,
    )
    inverted = evaluate_candidate(
        predictions=positive,
        raw_returns=raw,
        candidate_kind=CandidateKind.LGBM_REGRESSOR,
        orientation=ScoreOrientation.INVERTED,
        topk=5,
    )

    assert original.score_direction.recommendation == DirectionRecommendation.KEEP.value
    assert original.score_direction.top_minus_bottom_spread > 0
    assert "applied orientation is aligned" in original.strength_rationale

    assert inverted.score_direction.recommendation == DirectionRecommendation.INVERT.value
    assert inverted.score_direction.top_minus_bottom_spread < 0
    assert "still points backward" in inverted.weakness_rationale
    assert "direction aligned (invert)" not in inverted.strength_rationale


def test_compute_direction_diagnostics_no_signal_on_empty_input() -> None:
    index = pd.MultiIndex.from_arrays(
        [[], []],
        names=["datetime", "instrument"],
    )
    diagnostics = compute_direction_diagnostics(
        pd.Series([], index=index, dtype=float),
        pd.Series([], index=index, dtype=float),
    )
    assert diagnostics.recommendation == DirectionRecommendation.NO_SIGNAL.value


def test_run_signal_discovery_comparison_reports_research_candidates(tmp_path: Path) -> None:
    raw = _make_raw_returns(n_dates=20, n_stocks=40)
    pred = _make_predictions(raw, strength=0.4)
    factor = _make_factor(raw)

    report = run_signal_discovery_comparison(
        market="us",
        lgbm_predictions=pred,
        raw_returns=raw,
        factor_baseline_predictions=factor,
        topk=5,
        output_dir=tmp_path,
    )

    assert report.label_horizon == 10
    assert report.rebalance_days == 10
    assert len(report.candidates) == 6
    assert set(report.promoted).isdisjoint(report.research_only)
    assert report.summary["n_candidates"] == len(report.candidates)
    assert report.summary["data_contracts"]["economic_returns"] == (
        "raw_forward_return with horizon=10"
    )

    path = tmp_path / "us_signal_discovery_report.json"
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0"
    assert loaded["summary"]["best_candidate"]


def test_processed_label_rejected_by_economic_evaluation() -> None:
    raw = _make_raw_returns(n_dates=12, n_stocks=30)
    pred = _make_predictions(raw)
    processed = raw.copy()
    processed.attrs["provenance"] = "CSRankNorm_label"

    with pytest.raises(ValueError, match="raw_forward_return"):
        evaluate_candidate(
            predictions=pred,
            raw_returns=processed,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
        )


def test_report_status_membership_matches_candidate_status() -> None:
    raw = _make_raw_returns(n_dates=15, n_stocks=35)
    pred = _make_predictions(raw)
    report = run_signal_discovery_comparison(
        market="us",
        lgbm_predictions=pred,
        raw_returns=raw,
        factor_baseline_predictions=None,
        topk=5,
    )

    labels = {
        f"{candidate.candidate_kind.value}/{candidate.orientation.value}"
        for candidate in report.candidates
    }
    assert labels == set(report.promoted) | set(report.research_only)

    for candidate in report.candidates:
        label = f"{candidate.candidate_kind.value}/{candidate.orientation.value}"
        if candidate.status == CandidateStatus.PROMOTED:
            assert label in report.promoted
        else:
            assert label in report.research_only
