from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_23_xgb_lambdarank_data import (
    ACTION_ORDER,
    action_rank_labels,
)
from src.research.v4_23_xgb_lambdarank_model import (
    fit_ranker,
    predict,
    select_from_scores,
)
from src.research.v4_23_xgb_lambdarank_policy import strategy_daily

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_xgb_lambdarank_state_machine_v4_23_research.yaml"
)


def _micro_contract() -> dict:
    return {
        "model": {
            "objective": "rank:ndcg",
            "eval_metric": "ndcg@1",
            "tree_method": "hist",
            "max_depth": 2,
            "learning_rate": 0.05,
            "boosting_rounds": 5,
            "min_child_weight": 1.0,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "reg_lambda": 1.0,
            "reg_alpha": 0.0,
            "gamma": 0.0,
            "max_bin": 32,
            "seed": 7,
            "nthread": 1,
        },
        "decision": {
            "holding_sessions": 10,
            "transaction_cost_bps_per_turnover_unit": 10.0,
        },
    }


def test_contract_freezes_39_inputs_and_ranker_parameters() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    features = contract["features"]
    total = sum(
        len(features[key])
        for key in ("market", "credit_duration", "state", "action")
    )
    assert total == 39 == features["total_inputs"]
    assert contract["model"]["objective"] == "rank:ndcg"
    assert contract["model"]["eval_metric"] == "ndcg@1"
    assert contract["model"]["max_depth"] == 3
    assert contract["model"]["boosting_rounds"] == 300
    assert contract["decision"]["holding_sessions"] == 10
    assert contract["decision"]["embargo_sessions"] == 10


def test_action_rank_labels_are_within_date_and_deterministic() -> None:
    returns = pd.Series(
        {
            "defense": -0.01,
            "balanced": 0.01,
            "core": 0.03,
            "leveraged": 0.02,
            "accelerated": -0.02,
        }
    )
    labels = action_rank_labels(returns)
    assert labels["core"] == 4
    assert labels["leveraged"] == 3
    assert labels["accelerated"] == 0
    assert sorted(labels.astype(int).tolist()) == [0, 1, 2, 3, 4]


def test_grouped_ranker_scores_one_complete_action_group_per_date() -> None:
    dates = pd.date_range("2020-01-01", periods=12, freq="B")
    rows = []
    for group_number, date in enumerate(dates):
        for action_number, action in enumerate(ACTION_ORDER):
            rows.append(
                {
                    "decision_date": date,
                    "action": action,
                    "action_order": action_number,
                    "feature_a": float(group_number),
                    "feature_b": float(action_number),
                    "relevance": action_number,
                    "realized_action_return": float(action_number) / 100.0,
                }
            )
    frame = pd.DataFrame(rows)
    bundle = fit_ranker(frame, ("feature_a", "feature_b"), _micro_contract())
    scores = predict(bundle, frame)
    assert bundle.training_groups == len(dates)
    assert bundle.training_rows == len(dates) * 5
    assert scores.shape == (len(frame),)
    assert np.isfinite(scores).all()


def test_selection_uses_highest_score_and_true_group_regret() -> None:
    date = pd.Timestamp("2022-01-03")
    frame = pd.DataFrame(
        {
            "decision_date": [date] * 5,
            "action": list(ACTION_ORDER),
            "action_order": list(range(5)),
            "score": [0.0, 0.1, 1.0, 0.2, 0.3],
            "relevance": [0, 1, 3, 2, 4],
            "realized_action_return": [-0.02, -0.01, 0.03, 0.01, 0.05],
        }
    )
    selected = select_from_scores(frame)
    assert len(selected) == 1
    assert selected.iloc[0]["action"] == "core"
    assert np.isclose(selected.iloc[0]["selected_regret"], 0.02)
    assert selected.iloc[0]["selected_realized_rank"] == 2


def test_strategy_daily_starts_after_signal_close_and_charges_exact_turnover() -> None:
    dates = pd.date_range("2021-01-01", periods=30, freq="B")
    opens = 100.0 * np.cumprod(np.full(len(dates), 1.001))
    bars = {
        symbol: pd.DataFrame({"date": dates, "open": opens, "close": opens})
        for symbol in ("QQQ", "TQQQ", "BIL")
    }
    selected = pd.DataFrame(
        {
            "decision_date": [dates[5]],
            "action": ["core"],
        }
    )
    result = strategy_daily(
        selected,
        bars,
        _micro_contract(),
        cash_symbol="BIL",
        strategy_name="test",
    )
    assert len(result.daily) == 10
    assert result.daily.index[0] == dates[6]
    assert np.isclose(result.daily.iloc[0]["turnover_units"], 1.0)
    assert np.isclose(result.daily.iloc[0]["transaction_cost"], 0.001)
    assert np.isclose(result.daily.iloc[1:]["transaction_cost"].sum(), 0.0)
