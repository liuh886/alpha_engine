from __future__ import annotations

import json

import pandas as pd

from src.research.daily_ranker_model import (
    fit_xgb_daily_ranker,
    predict_xgb_daily_ranker,
)
from src.research.xgb_ranker_explainability import (
    attach_factor_contributions,
    build_xgb_pred_contribs,
)


def _frame(dates: list[str]) -> pd.DataFrame:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(dates), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame(
        {
            "f_momentum": [0.1, 0.4, 0.8] * len(dates),
            "f_volatility": [0.8, 0.3, 0.1] * len(dates),
        },
        index=index,
    )


def _fit():
    train = _frame(["2026-07-01", "2026-07-02"])
    target = pd.Series(
        [0.1, 0.5, 0.9, 0.2, 0.6, 0.8],
        index=train.index,
        name="rank_target",
    )
    return fit_xgb_daily_ranker(train, target, [3, 3], num_boost_round=8)


def _build(test: pd.DataFrame):
    fit = _fit()
    scores = predict_xgb_daily_ranker(fit, test)
    return build_xgb_pred_contribs(
        model=fit.model,
        features=test,
        scores=scores,
        column_to_factor_id={
            "f_momentum": "ohlcv.momentum.test",
            "f_volatility": "ohlcv.volatility.test",
        },
        instruments=["A", "B"],
        decision_role="selected_holding",
    )


def test_native_pred_contribs_reconcile_and_bind_canonical_factor_ids() -> None:
    evidence = _build(_frame(["2026-07-03"]))

    assert evidence["method"] == "xgboost_pred_contribs"
    assert [row["instrument"] for row in evidence["rows"]] == ["A", "B"]
    for row in evidence["rows"]:
        factor_ids = {item["factor_id"] for item in row["factor_contributions"]}
        assert factor_ids == {"ohlcv.momentum.test", "ohlcv.volatility.test"}
        assert row["decision_role"] == "selected_holding"

    snapshot = {
        "factors": [
            {"factor_id": "ohlcv.momentum.test", "reference": {"universe_mean": 0.2}},
            {"factor_id": "ohlcv.volatility.test", "reference": {"universe_mean": 0.3}},
        ]
    }
    enriched = attach_factor_contributions(snapshot, evidence)
    for factor in enriched["factors"]:
        contributions = factor["reference"]["model_contributions"]
        assert [row["instrument"] for row in contributions] == ["A", "B"]
        assert all(row["decision_role"] == "selected_holding" for row in contributions)


def test_missing_feature_observations_publish_as_json_null_not_nan() -> None:
    test = _frame(["2026-07-03"])
    test.loc[(pd.Timestamp("2026-07-03"), "A"), "f_momentum"] = float("nan")

    evidence = _build(test)
    row_a = next(row for row in evidence["rows"] if row["instrument"] == "A")
    missing = next(
        row for row in row_a["factor_contributions"] if row["factor_id"] == "ohlcv.momentum.test"
    )
    assert missing["value"] is None
    assert missing["percentile"] is None

    snapshot = {
        "factors": [
            {"factor_id": "ohlcv.momentum.test", "reference": {}},
            {"factor_id": "ohlcv.volatility.test", "reference": {}},
        ]
    }
    enriched = attach_factor_contributions(snapshot, evidence)
    json.dumps(evidence, allow_nan=False)
    json.dumps(enriched, allow_nan=False)

    momentum = next(
        row for row in enriched["factors"] if row["factor_id"] == "ohlcv.momentum.test"
    )
    contribution_a = next(
        row for row in momentum["reference"]["model_contributions"] if row["instrument"] == "A"
    )
    assert contribution_a["value"] is None
    assert contribution_a["percentile"] is None
