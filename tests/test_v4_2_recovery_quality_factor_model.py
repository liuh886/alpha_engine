from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_recovery_quality_factor_model import (
    _episode_budget_trace,
    _forward_sum,
    _prediction_metrics,
    _state_one_age,
    fit_walk_forward_factor_model,
    run_factor_budget_backtest,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_v4_2_recovery_quality_factor_v4_11_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_forward_sum_starts_after_signal_close() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = _forward_sum(series, 2)
    assert result.iloc[0] == 5.0
    assert result.iloc[1] == 7.0
    assert result.iloc[2:].isna().all()


def test_single_class_validation_keeps_non_auc_evidence() -> None:
    table = pd.DataFrame(
        {
            "probability": [0.10, 0.30, 0.70, 0.90],
            "positive_marginal_return": [1, 1, 1, 1],
            "future_marginal_log_return_10d": [0.01, 0.02, 0.03, 0.04],
        }
    )
    metrics = _prediction_metrics(table, require_both_classes=False)
    assert np.isnan(metrics["roc_auc"])
    assert metrics["class_count"] == 1
    assert metrics["top_bottom_quartile_spread"] > 0.0


def test_state_one_age_resets_outside_state_one() -> None:
    states = pd.Series([0, 1, 1, 2, 1, 1, 1, 0])
    assert _state_one_age(states).tolist() == [0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 3.0, 0.0]


def test_episode_budget_reads_prior_close_once() -> None:
    index = pd.date_range("2024-01-02", periods=8, freq="B")
    states = pd.Series([1, 1, 2, 2, 1, 2, 2, 0], index=index)
    probabilities = pd.Series([0.20, 0.70, 0.10, 0.10, 0.30, 0.90, 0.90, 0.90], index=index)
    trace = _episode_budget_trace(states, probabilities, _contract())
    assert trace.loc[index[2], "factor_bucket"] == "high"
    assert trace.loc[index[3], "factor_bucket"] == "high"
    assert trace.loc[index[2], "factor_probability_at_entry"] == 0.70
    assert trace.loc[index[5], "factor_bucket"] == "low"
    assert trace.loc[index[6], "factor_bucket"] == "low"
    assert trace.loc[index[5], "factor_probability_at_entry"] == 0.30
    assert int(trace["state_2_episode_entry"].sum()) == 2


def _synthetic_baseline() -> StrategyResult:
    index = pd.date_range("2024-01-02", periods=10, freq="B")
    states = pd.Series([1, 1, 2, 2, 2, 1, 2, 2, 1, 0], index=index)
    daily = pd.DataFrame(index=index)
    daily["position_state"] = states
    daily["position_label"] = states.map({0: "defensive", 1: "attack", 2: "leveraged_attack"})
    daily["executed_reason"] = "test"
    daily["decision_state"] = states
    daily["QQQI_next_open_return"] = 0.001
    daily["QQQ_next_open_return"] = [0.001, 0.002, 0.010, -0.005, 0.004, 0.001, 0.003, 0.002, 0.001, 0.0]
    daily["TQQQ_next_open_return"] = [0.002, 0.004, 0.030, -0.015, 0.012, 0.003, 0.009, 0.006, 0.003, 0.0]
    daily["weight_QQQI"] = np.where(states.eq(0), 1.0, np.where(states.eq(1), 0.5, 0.0))
    daily["weight_QQQ"] = np.where(states.eq(1), 0.5, np.where(states.eq(2), 0.25, 0.0))
    daily["weight_TQQQ"] = np.where(states.eq(2), 0.75, 0.0)
    daily["turnover_units"] = 0.0
    daily["transaction_cost"] = 0.0
    daily["net_return"] = (
        daily["weight_QQQI"] * daily["QQQI_next_open_return"]
        + daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
    )
    daily["gross_return"] = daily["net_return"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    return StrategyResult("baseline", daily, pd.DataFrame(), {})


def test_joint_budget_changes_only_state_two_weights() -> None:
    baseline = _synthetic_baseline()
    probability = pd.Series(
        [0.20, 0.70, 0.50, 0.50, 0.50, 0.30, 0.50, 0.50, 0.50, 0.50],
        index=baseline.daily.index,
    )
    result = run_factor_budget_backtest(
        baseline, probability, _contract(), "factor_joint_budget"
    )
    assert result.daily["position_state"].equals(baseline.daily["position_state"])
    first_episode = result.daily.iloc[2:5]
    second_episode = result.daily.iloc[6:8]
    assert np.allclose(first_episode["weight_TQQQ"], 1.0)
    assert np.allclose(first_episode["weight_QQQ"], 0.0)
    assert np.allclose(second_episode["weight_TQQQ"], 0.5)
    assert np.allclose(second_episode["weight_QQQ"], 0.5)
    outside = result.daily.loc[result.daily["position_state"].ne(2)]
    baseline_outside = baseline.daily.loc[baseline.daily["position_state"].ne(2)]
    assert np.allclose(outside["weight_QQQI"], baseline_outside["weight_QQQI"])
    assert np.allclose(outside["weight_QQQ"], baseline_outside["weight_QQQ"])
    assert np.allclose(outside["weight_TQQQ"], baseline_outside["weight_TQQQ"])


def test_walk_forward_reserves_2024_plus() -> None:
    contract = _contract()
    index = pd.date_range("2011-01-03", "2025-12-31", freq="B")
    rng = np.random.default_rng(7)
    feature_names = list(contract["features"])
    frame = pd.DataFrame(index=index)
    latent = rng.normal(size=len(index))
    for number, feature in enumerate(feature_names, start=1):
        frame[feature] = latent * (0.05 * number) + rng.normal(scale=1.0, size=len(index))
    continuous = 0.02 * latent + rng.normal(scale=0.03, size=len(index))
    frame["future_marginal_log_return_10d"] = continuous
    frame["positive_marginal_return"] = continuous > 0.0
    frame["position_state"] = 1
    frame["decision_state"] = 1
    frame["eligible_for_model"] = True
    frame["QQQ_next_open_return"] = 0.0
    frame["TQQQ_next_open_return"] = 0.0
    output = fit_walk_forward_factor_model(frame, contract)
    assert pd.Timestamp(output.aggregate_metrics["final_training_end"]) < pd.Timestamp("2024-01-02")
    assert output.holdout_predictions.index.min() >= pd.Timestamp("2024-01-02")
    assert set(output.feature_names) == set(feature_names)
    assert output.fold_metrics["validation_year"].max() == 2023
