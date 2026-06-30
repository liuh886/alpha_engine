"""Contract tests for notebook-friendly core interfaces."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.metrics import compute_spread_metrics
from src.core.portfolio import build_rolling_portfolio
from src.core.selection import GuardrailInputs, select_bottomn, select_topn
from src.core.signals import generate_scores


class DummyRegressor:
    def predict(self, features):
        return np.asarray(features["x"], dtype=float) * 2.0


class DummyClassifier:
    def predict_proba(self, features):
        positive = np.asarray(features["x"], dtype=float)
        return np.column_stack([1.0 - positive, positive])

    def predict(self, features):
        return np.zeros(len(features))


def test_generate_scores_regressor_preserves_index():
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2024-01-02")], ["A", "B"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"x": [0.2, 0.4]}, index=index)

    scores = generate_scores(DummyRegressor(), features)

    assert list(scores.index) == list(index)
    assert scores.tolist() == [0.4, 0.8]


def test_generate_scores_classifier_uses_predict_proba():
    features = pd.DataFrame({"x": [0.2, 0.8]}, index=["A", "B"])

    scores = generate_scores(DummyClassifier(), features)

    assert scores.tolist() == [0.2, 0.8]


def test_select_topn_applies_long_guardrail_only():
    scores = pd.Series({"A": 0.9, "B": 0.8, "C": -0.1, "D": 0.7})
    guardrail = GuardrailInputs(
        prices=pd.Series({"A": 90.0, "B": 120.0, "D": 130.0}),
        moving_average=pd.Series({"A": 100.0, "B": 100.0, "D": 100.0}),
        require_positive_score=True,
    )

    selected = select_topn(scores, n=2, guardrail=guardrail)

    assert selected == ["B", "D"]


def test_select_bottomn_has_no_guardrail():
    scores = pd.Series({"A": -0.5, "B": 0.1, "C": -0.2})

    selected = select_bottomn(scores, n=2)

    assert selected == ["A", "C"]


def test_build_rolling_portfolio_sleeve_weights():
    dates = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    signals = {dates[0]: ["A", "B"], dates[1]: ["B", "C"]}

    portfolio = build_rolling_portfolio(signals, holding_days=2)

    assert portfolio.loc[dates[0], "weights"] == {"A": 0.25, "B": 0.25}
    assert portfolio.loc[dates[1], "weights"] == {"A": 0.25, "B": 0.5, "C": 0.25}
    assert portfolio.loc[dates[1], "gross_weight"] == 1.0


def test_compute_spread_metrics_aligns_inputs():
    long_returns = pd.Series([0.02, 0.01], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    short_returns = pd.Series([0.01, -0.02], index=pd.to_datetime(["2024-01-03", "2024-01-04"]))

    metrics = compute_spread_metrics(long_returns, short_returns)
    spread = metrics["spread_series"]

    assert spread.loc[pd.Timestamp("2024-01-02")] == 0.02
    assert spread.loc[pd.Timestamp("2024-01-03")] == 0.0
    assert spread.loc[pd.Timestamp("2024-01-04")] == 0.02
