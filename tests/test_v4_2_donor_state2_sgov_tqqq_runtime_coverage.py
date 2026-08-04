from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_2_donor_state2_sgov_tqqq_runtime_coverage import (
    _coverage_safe_variant_weight,
    build_all_target_state2_prediction_rows,
    predict_target_episodes_with_coverage,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_donor_state2_sgov_tqqq_v4_13_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _row(contract: dict, *, year: int, number: int) -> dict:
    row = {
        "asset_episode_id": f"QQQ_{number:03d}",
        "underlying": "QQQ",
        "leveraged": "TQQQ",
        "signal_close_date": pd.Timestamp(year=year, month=5, day=1),
        "execution_date": pd.Timestamp(year=year, month=5, day=2),
        "episode_end_date": pd.Timestamp(year=year, month=5, day=15),
        "holding_sessions": 10,
        "signal_row_available": True,
    }
    for feature in contract["features"]:
        row[feature] = 0.1 + 0.01 * number
    return row


def _donor(contract: dict) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(31)
    for number in range(20):
        latent = 1.0 if number % 2 == 0 else -1.0
        row = {
            "underlying": "SPY" if number < 10 else "IWM",
            "positive_episode_excess": int(latent > 0),
            "signal_close_date": pd.Timestamp("2010-01-04")
            + pd.Timedelta(days=number * 100),
        }
        for feature in contract["features"]:
            row[feature] = latent + rng.normal(scale=0.1)
        rows.append(row)
    return pd.DataFrame(rows)


def test_unavailable_year_retains_baseline_without_fake_probability() -> None:
    contract = _contract()
    target = pd.DataFrame([_row(contract, year=2011, number=1)])
    donor = pd.DataFrame(columns=[
        "underlying",
        "positive_episode_excess",
        "signal_close_date",
        *contract["features"],
    ])
    predicted = predict_target_episodes_with_coverage(
        target, donor, contract
    )
    assert not bool(predicted.iloc[0]["probability_available"])
    assert predicted.iloc[0]["probability"] == -1.0
    assert predicted.iloc[0]["probability_bucket"] == "unavailable"
    for variant in (
        "state2_cash_residual_swap",
        "state2_defensive_only",
        "state2_offensive_only",
        "state2_joint_donor_budget",
    ):
        assert _coverage_safe_variant_weight("unavailable", variant) == 0.75


def test_available_year_uses_donor_only_model() -> None:
    contract = _contract()
    target = pd.DataFrame([_row(contract, year=2018, number=1)])
    donor = _donor(contract)
    predicted = predict_target_episodes_with_coverage(
        target, donor, contract
    )
    assert bool(predicted.iloc[0]["probability_available"])
    assert 0.0 <= float(predicted.iloc[0]["probability"]) <= 1.0
    assert predicted.iloc[0]["probability_bucket"] in {
        "low",
        "medium",
        "high",
    }
    assert predicted.iloc[0]["training_episode_count"] == len(donor)


def test_missing_target_feature_uses_frozen_median_imputer() -> None:
    contract = _contract()
    target_row = _row(contract, year=2018, number=1)
    target_row[contract["features"][0]] = np.nan
    target = pd.DataFrame([target_row])
    predicted = predict_target_episodes_with_coverage(
        target, _donor(contract), contract
    )
    assert bool(predicted.iloc[0]["probability_available"])
    assert 0.0 <= float(predicted.iloc[0]["probability"]) <= 1.0


def test_builder_retains_episode_with_missing_features() -> None:
    contract = _contract()
    index = pd.date_range("2018-01-02", periods=6, freq="B")
    baseline = pd.DataFrame(
        {"position_state": [1, 1, 2, 2, 2, 1]}, index=index
    )
    feature_frame = pd.DataFrame(
        {feature: [np.nan] * len(index) for feature in contract["features"]},
        index=index,
    )
    rows = build_all_target_state2_prediction_rows(
        baseline, feature_frame, features=contract["features"]
    )
    assert len(rows) == 1
    assert rows.iloc[0]["execution_date"] == index[2]
    assert rows.iloc[0]["episode_end_date"] == index[4]
    assert bool(rows.iloc[0]["signal_row_available"])
