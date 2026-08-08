from __future__ import annotations

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


def test_native_pred_contribs_reconcile_and_bind_canonical_factor_ids() -> None:
    train = _frame(["2026-07-01", "2026-07-02"])
    target = pd.Series(
        [0.1, 0.5, 0.9, 0.2, 0.6, 0.8],
        index=train.index,
        name="rank_target",
    )
    fit = fit_xgb_daily_ranker(train, target, [3, 3], num_boost_round=8)
    test = _frame(["2026-07-03"])
    scores = predict_xgb_daily_ranker(fit, test)

    evidence = build_xgb_pred_contribs(
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
