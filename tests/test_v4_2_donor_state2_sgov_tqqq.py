from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_donor_state2_sgov_tqqq import (
    _donor_gate,
    _episode_bucket_trace,
    _state_age,
    fit_donor_state2_model,
    predict_target_episodes_walk_forward,
    run_state2_cash_budget,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_donor_state2_sgov_tqqq_v4_13_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_target_symbols_are_excluded_from_donor_training() -> None:
    contract = _contract()
    excluded = set(contract["boundaries"]["target_symbols_excluded_from_training"])
    donors = set(contract["data"]["donor_pairs"])
    leveraged = set(contract["data"]["donor_pairs"].values())
    assert not donors.intersection(excluded)
    assert not leveraged.intersection(excluded)


def test_state_age_resets_outside_state_one() -> None:
    states = pd.Series([0, 1, 1, 2, 1, 1, 0])
    assert _state_age(states, 1).tolist() == [0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0]


def _synthetic_donor_episodes() -> pd.DataFrame:
    contract = _contract()
    assets = list(contract["data"]["donor_pairs"])
    rng = np.random.default_rng(23)
    rows: list[dict] = []
    for cluster in range(12):
        sign = 1.0 if cluster % 2 == 0 else -1.0
        for asset_number, asset in enumerate(assets):
            latent = sign + 0.08 * asset_number + rng.normal(scale=0.05)
            row = {
                "asset_episode_id": f"{asset}_{cluster:03d}",
                "underlying": asset,
                "leveraged": contract["data"]["donor_pairs"][asset],
                "cash": "BIL",
                "macro_cluster_id": f"macro_{cluster:03d}",
                "signal_close_date": pd.Timestamp("2010-01-04")
                + pd.Timedelta(days=cluster * 300 + asset_number),
                "execution_date": pd.Timestamp("2010-01-05")
                + pd.Timedelta(days=cluster * 300 + asset_number),
                "episode_end_date": pd.Timestamp("2010-01-20")
                + pd.Timedelta(days=cluster * 300 + asset_number),
                "holding_sessions": 10,
                "positive_episode_excess": int(latent > 0.0),
                "episode_excess_log_return": 0.04 * latent,
            }
            for number, feature in enumerate(contract["features"], start=1):
                row[feature] = latent * (1.0 + number * 0.01) + rng.normal(
                    scale=0.03
                )
            rows.append(row)
    return pd.DataFrame(rows)


def test_macro_and_loao_models_exclude_target_and_pass_synthetic_signal() -> None:
    episodes = _synthetic_donor_episodes()
    model = fit_donor_state2_model(episodes, _contract())
    assert len(model.cluster_oof) == len(episodes)
    assert len(model.loao_predictions) == len(episodes)
    assert "QQQ" not in set(model.donor_episodes["underlying"])
    assert model.cluster_metrics["roc_auc"] > 0.90
    assert model.cluster_metrics["spearman_ic"] > 0.80
    assert model.loao_metrics["roc_auc"] > 0.90
    assert model.loao_metrics["spearman_ic"] > 0.80
    assert _donor_gate(model, _contract())["passed"]


def test_target_walk_forward_uses_only_earlier_donor_episodes() -> None:
    donor = _synthetic_donor_episodes()
    target = donor.iloc[:2].copy()
    target["underlying"] = "QQQ"
    target["leveraged"] = "TQQQ"
    target["signal_close_date"] = pd.to_datetime(["2017-05-01", "2018-05-01"])
    target["execution_date"] = pd.to_datetime(["2017-05-02", "2018-05-02"])
    target["episode_end_date"] = pd.to_datetime(["2017-05-15", "2018-05-15"])
    target["asset_episode_id"] = ["QQQ_001", "QQQ_002"]
    predicted = predict_target_episodes_walk_forward(target, donor, _contract())
    for row in predicted.itertuples(index=False):
        assert pd.Timestamp(row.training_cutoff) == pd.Timestamp(
            year=pd.Timestamp(row.signal_close_date).year, month=1, day=1
        )
        eligible = donor.loc[
            pd.to_datetime(donor["signal_close_date"]).lt(row.training_cutoff)
        ]
        assert row.training_episode_count == len(eligible)
        assert row.training_asset_count == eligible["underlying"].nunique()


def _synthetic_baseline() -> StrategyResult:
    index = pd.date_range("2018-01-02", periods=12, freq="B")
    states = pd.Series([1, 1, 2, 2, 2, 1, 1, 2, 2, 1, 0, 0], index=index)
    daily = pd.DataFrame(index=index)
    daily["position_state"] = states
    daily["weight_QQQI"] = np.where(states.eq(0), 1.0, np.where(states.eq(1), 0.5, 0.0))
    daily["weight_QQQ"] = np.where(states.eq(1), 0.5, np.where(states.eq(2), 0.25, 0.0))
    daily["weight_TQQQ"] = np.where(states.eq(2), 0.75, 0.0)
    daily["QQQI_next_open_return"] = 0.001
    daily["QQQ_next_open_return"] = 0.002
    daily["TQQQ_next_open_return"] = [
        0.003,
        0.003,
        0.02,
        -0.01,
        0.015,
        0.002,
        0.002,
        -0.02,
        0.01,
        0.002,
        0.001,
        0.001,
    ]
    daily["net_return"] = (
        daily["weight_QQQI"] * daily["QQQI_next_open_return"]
        + daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
    )
    daily["gross_return"] = daily["net_return"]
    daily["turnover_units"] = 0.0
    daily["transaction_cost"] = 0.0
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    return StrategyResult("baseline", daily, pd.DataFrame(), {})


def _target_predictions(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset_episode_id": ["QQQ_001", "QQQ_002"],
            "execution_date": [index[2], index[7]],
            "episode_end_date": [index[4], index[8]],
            "probability": [0.80, 0.20],
            "probability_bucket": ["high", "low"],
        }
    )


def test_episode_trace_freezes_bucket_for_entire_state2_episode() -> None:
    baseline = _synthetic_baseline()
    trace = _episode_bucket_trace(
        baseline.daily, _target_predictions(baseline.daily.index)
    )
    assert trace.loc[baseline.daily.index[2:5], "probability_bucket"].eq("high").all()
    assert trace.loc[baseline.daily.index[7:9], "probability_bucket"].eq("low").all()


def test_joint_budget_changes_only_state2_and_preserves_trace() -> None:
    baseline = _synthetic_baseline()
    index = baseline.daily.index
    result = run_state2_cash_budget(
        baseline,
        pd.Series(0.0001, index=index),
        _target_predictions(index),
        index,
        _contract(),
        "state2_joint_donor_budget",
    )
    assert result.daily["position_state"].equals(baseline.daily["position_state"])
    outside = result.daily["position_state"].ne(2)
    for asset in ("QQQI", "QQQ", "TQQQ"):
        assert np.allclose(
            result.daily.loc[outside, f"weight_{asset}"],
            baseline.daily.loc[outside, f"weight_{asset}"],
        )
    assert np.allclose(result.daily.loc[index[2:5], "weight_TQQQ"], 1.0)
    assert np.allclose(result.daily.loc[index[2:5], "weight_cash"], 0.0)
    assert np.allclose(result.daily.loc[index[7:9], "weight_TQQQ"], 0.5)
    assert np.allclose(result.daily.loc[index[7:9], "weight_cash"], 0.5)
    weights = result.daily[["weight_QQQI", "weight_QQQ", "weight_TQQQ", "weight_cash"]]
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert np.allclose(
        result.daily["transaction_cost"],
        result.daily["turnover_units"] * 0.001,
    )
