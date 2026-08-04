from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_20_credit_duration_action_policy import (
    _build_shared_models,
    _calibration_gate,
    _calibration_slope,
)

CONTRACT_PATH = Path(
    "configs/research_paradigms/"
    "qqqi_credit_duration_action_policy_v4_20_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _synthetic_frame() -> tuple[
    pd.DataFrame, tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    index = pd.date_range("2010-01-04", "2024-01-31", freq="B")
    location = np.arange(len(index), dtype=float)
    base = tuple(f"base_{position}" for position in range(29))
    credit = tuple(f"credit_{position}" for position in range(8))
    targets = tuple(
        _contract()["actions"][action]["target"]
        for action in (
            "cash_defense",
            "broad_equity",
            "nasdaq_core",
            "nasdaq_acceleration",
        )
    )
    frame = pd.DataFrame(index=index)
    for position, feature in enumerate(base):
        frame[feature] = np.sin(location / (position + 7.0))
    for position, feature in enumerate(credit):
        frame[feature] = np.cos(location / (position + 11.0))
    for position, target in enumerate(targets):
        frame[target] = (
            0.01 * np.sin(location / (position + 13.0))
            + 0.003 * frame[credit[position]]
        )
    frame["global_training_sample"] = (
        location.astype(int) % 10
    ) == 0
    frame["qqq_distance_ma20"] = 0.01
    frame["qqq_distance_ma200"] = 0.10
    frame["voo_distance_ma200"] = 0.10
    frame["vol_max_percentile_252"] = 0.50
    frame["v4_2_execution_state"] = location.astype(int) % 3
    return frame, base, credit, targets


def test_contract_freezes_complete_37_input_candidate() -> None:
    contract = _contract()
    credit = contract["credit_duration_block"]["features"]
    assert len(credit) == 8
    assert len(set(credit)) == 8
    assert contract["base_comparator"]["total_inputs"] == 29
    assert contract["credit_duration_block"]["candidate_total_inputs"] == 37
    assert contract["model"]["alpha"] == 100.0
    assert not contract["model"]["feature_selection_allowed"]
    assert not contract["model"]["added_interactions_allowed"]


def test_shared_models_use_identical_rows_and_ten_session_samples() -> None:
    frame, base, credit, targets = _synthetic_frame()
    frame.loc[frame.index[1250:1260], credit[0]] = np.nan
    base_oof, candidate_oof, _, coverage, _ = _build_shared_models(
        frame,
        base,
        base + credit,
        targets,
        _contract(),
    )
    assert base_oof.index.equals(candidate_oof.index)
    assert coverage["base_candidate_training_rows_identical"].all()
    assert coverage["base_candidate_test_rows_identical"].all()
    assert (coverage["training_samples"] >= 100).all()
    for start, end in zip(
        coverage["training_start"], coverage["training_end"]
    ):
        sampled = frame.loc[start:end]
        sampled = sampled.loc[sampled["global_training_sample"]]
        sampled = sampled.dropna(subset=list(base + credit) + list(targets))
        positions = frame.index.get_indexer(sampled.index)
        assert (np.diff(positions) >= 10).all()


def test_outer_training_ends_before_test_by_embargo() -> None:
    frame, base, credit, targets = _synthetic_frame()
    _, _, _, coverage, _ = _build_shared_models(
        frame,
        base,
        base + credit,
        targets,
        _contract(),
    )
    for row in coverage.itertuples(index=False):
        train_location = frame.index.get_loc(pd.Timestamp(row.training_end))
        test_location = frame.index.get_loc(pd.Timestamp(row.test_start))
        assert test_location - train_location >= 11


def test_calibration_slope_recovers_linear_relation() -> None:
    prediction = pd.Series(np.linspace(-0.02, 0.02, 200))
    realized = 0.001 + 1.2 * prediction
    assert np.isclose(_calibration_slope(prediction, realized), 1.2)


def test_calibration_gate_is_independent_and_strict() -> None:
    metrics = pd.DataFrame(
        {
            "action": ["a", "b", "c", "d"],
            "base_mae": [0.01] * 4,
            "candidate_mae": [0.009, 0.010, 0.0104, 0.0104],
            "candidate_base_mae_ratio": [0.9, 1.0, 1.04, 1.04],
            "candidate_bias": [0.001, -0.001, 0.002, -0.002],
            "candidate_calibration_slope": [0.8, 1.0, 1.2, 0.2],
            "candidate_high_score_observations": [20, 20, 20, 20],
            "candidate_high_score_mean_realized": [0.01, 0.005, 0.002, -0.001],
            "candidate_high_score_mae": [0.008, 0.008, 0.008, 0.008],
            "base_error_on_candidate_high_score_dates": [0.009] * 4,
        }
    )
    gate = _calibration_gate(metrics, _contract())
    assert gate["passed"]
    broken = metrics.copy()
    broken.loc[0, "candidate_base_mae_ratio"] = 1.20
    assert not _calibration_gate(broken, _contract())["passed"]


def test_phase2_cannot_directly_promote_or_change_alerts() -> None:
    contract = _contract()
    assert contract["boundaries"]["historical_success_authorizes_shadow_only"]
    assert contract["boundaries"]["baseline_alerts_unchanged"]
    assert contract["boundaries"]["telegram_unchanged"]
    assert contract["boundaries"]["issue_348_unchanged"]
