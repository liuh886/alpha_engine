from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/research_experiments/us_x1_1_native_xgb_calibration_v1.yaml"
)


def _load_contract() -> dict:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _calibration_rows() -> list[dict]:
    rows = _load_contract()["native_calibrations"]
    assert isinstance(rows, list)
    return [dict(row) for row in rows]


def _without_id(row: dict) -> dict:
    result = dict(row)
    result.pop("calibration_id")
    return result


def test_native_grid_is_bound_to_us_x1_1_and_consumed_holdout_is_excluded() -> None:
    contract = _load_contract()
    assert contract["parent_model_id"] == "us_x1_1"
    assert contract["fixed_contract"]["feature_group"] == (
        "momentum_volatility_volume"
    )
    assert contract["windows"]["candidate_selection"] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]
    assert contract["windows"]["consumed_reporting_only"] == ["2026H1"]
    assert contract["windows"]["consumed_reporting_may_enter_selection"] is False
    assert contract["version_policy"]["may_propose_us_x1_2_candidate"] is True
    assert contract["version_policy"]["may_release_us_x1_2_automatically"] is False


def test_every_declared_native_calibration_has_a_unique_effective_identity() -> None:
    calibrations = [
        XGBNativeCalibration.from_dict(_without_id(row))
        for row in _calibration_rows()
    ]
    names = [calibration.name for calibration in calibrations]
    hashes = [calibration.identity_manifest()["identity_sha256"] for calibration in calibrations]
    assert len(calibrations) == 6
    assert len(names) == len(set(names))
    assert len(hashes) == len(set(hashes))
    for calibration in calibrations:
        manifest = calibration.identity_manifest()
        effective = manifest["effective_model_parameters"]
        declared = manifest["declared_parameters"]
        assert effective["learning_rate"] == declared["learning_rate"]
        assert effective["max_leaves"] == declared["max_leaves"]
        assert effective["min_child_weight"] == declared["min_child_weight"]
        assert manifest["num_boost_round"] == declared["num_boost_round"]


def test_changing_only_one_native_parameter_changes_the_contract() -> None:
    baseline = XGBNativeCalibration(n_gain_bins=7, num_boost_round=200)
    lower_rate = XGBNativeCalibration(
        n_gain_bins=7,
        num_boost_round=200,
        learning_rate=0.03,
    )
    assert baseline.name != lower_rate.name
    assert baseline.effective_model_parameters() != (
        lower_rate.effective_model_parameters()
    )
    assert baseline.identity_manifest()["identity_sha256"] != (
        lower_rate.identity_manifest()["identity_sha256"]
    )


def test_unknown_or_invalid_fields_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown XGBoost calibration fields"):
        XGBNativeCalibration.from_dict(
            {
                "n_gain_bins": 7,
                "num_boost_round": 200,
                "num_leaves": 31,
            }
        )
    with pytest.raises(ValueError, match="subsample must be in"):
        XGBNativeCalibration(
            n_gain_bins=7,
            num_boost_round=200,
            subsample=1.1,
        )


def test_fit_and_prediction_carry_effective_runtime_identity() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    instruments = ["A", "B", "C", "D"]
    index = pd.MultiIndex.from_product(
        [dates, instruments],
        names=["datetime", "instrument"],
    )
    rng = np.random.default_rng(42)
    features = pd.DataFrame(
        rng.normal(size=(len(index), 3)),
        index=index,
        columns=["f1", "f2", "f3"],
    )
    target = pd.Series(
        np.tile([0.0, 0.33, 0.66, 1.0], len(dates)),
        index=index,
        name="rank_target",
    )
    calibration = XGBNativeCalibration(
        n_gain_bins=5,
        num_boost_round=3,
        max_leaves=7,
        min_child_weight=2.0,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.9,
        seed=7,
    )
    result = fit_xgb_native_daily_ranker(
        features,
        target,
        [4, 4, 4],
        calibration=calibration,
    )
    scores = predict_xgb_native_daily_ranker(result, features)
    assert scores.shape == (len(index), 1)
    assert scores.attrs["model_type"] == "xgb_rank_ndcg_native_contract"
    assert scores.attrs["num_boost_round"] == 3
    assert scores.attrs["effective_runtime_parameters"] == (
        calibration.effective_model_parameters()
    )
    assert scores.attrs["parameter_identity_sha256"] == (
        calibration.identity_manifest()["identity_sha256"]
    )
