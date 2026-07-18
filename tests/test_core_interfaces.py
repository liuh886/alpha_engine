"""Contract tests for notebook-friendly core interfaces.

Tests target the authoritative current API — pure, stateless functions
that operate on pandas DataFrames/Series with MultiIndex panels and
return plain types (lists, dicts, dataclasses).  No I/O, no fixtures.

Current public API (src.core.__init__):
  generate_scores          — signals.py
  select_topk / select_bottomk  — selection.py
  build_rolling_portfolio  — portfolio.py (returns RollingPortfolioResult)
  compute_spread / compute_ic_series  — metrics.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.metrics import compute_ic_series, compute_spread
from src.core.portfolio import RollingPortfolioResult, build_rolling_portfolio
from src.core.selection import select_bottomk, select_topk
from src.core.signals import generate_scores


# ---------------------------------------------------------------------------
# Helpers — model-recording dummy for signal tests
# ---------------------------------------------------------------------------


class _RecordingDummy:
    """Records the last ndarray passed to predict; returns 2× first-column values."""

    def __init__(self):
        self.last_X: np.ndarray | None = None

    def predict(self, X: np.ndarray) -> np.ndarray:
        self.last_X = X.copy()
        return X[:, 0] * 2.0


# ---------------------------------------------------------------------------
# signals — generate_scores
# ---------------------------------------------------------------------------


def test_generate_scores_passes_cleaned_matrix():
    """model.predict receives the sanitised numeric ndarray, not a DataFrame."""
    dummy = _RecordingDummy()
    features = pd.DataFrame({"x": [0.2, 0.4], "y": [1.0, 2.0]})

    generate_scores(dummy, features)

    assert isinstance(dummy.last_X, np.ndarray)
    assert dummy.last_X.shape == (2, 2)
    np.testing.assert_array_almost_equal(dummy.last_X, [[0.2, 1.0], [0.4, 2.0]])


def test_generate_scores_preserves_index():
    """Output Series preserves the original index (including MultiIndex)."""
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2024-01-02")], ["A", "B"]],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"x": [0.2, 0.4]}, index=index)

    scores = generate_scores(_RecordingDummy(), features)

    assert list(scores.index) == list(index)
    np.testing.assert_array_almost_equal(scores.values, [0.4, 0.8])


def test_generate_scores_converts_nan_inf_to_zero():
    """NaN and ±Inf are replaced with 0 before model.predict sees the matrix."""
    dummy = _RecordingDummy()
    features = pd.DataFrame({"a": [np.nan, 1.0, np.inf], "b": [-np.inf, 2.0, 3.0]})

    generate_scores(dummy, features)

    expected = [[0.0, 0.0], [1.0, 2.0], [0.0, 3.0]]
    np.testing.assert_array_almost_equal(dummy.last_X, expected)


# ---------------------------------------------------------------------------
# selection — select_topk / select_bottomk
# ---------------------------------------------------------------------------


def test_select_topk_applies_long_guardrail_only():
    """Guardrail rejects: score <= min_score, or price below MA."""
    scores = pd.Series({"A": 0.9, "B": 0.8, "C": -0.1, "D": 0.7})
    prices = pd.Series({"A": 90.0, "B": 120.0, "D": 130.0})
    ma = pd.Series({"A": 100.0, "B": 100.0, "D": 100.0})

    selected = select_topk(scores, k=2, guardrail=True, prices=prices, ma=ma)

    # A rejected: score 0.9 > 0 but price 90 < MA 100
    # C rejected: score -0.1 <= min_score 0
    # B, D pass both gates
    assert selected == ["B", "D"]


def test_select_topk_guardrail_negative_score_rejected():
    """When guardrail=True, all negative-score tickers are filtered out."""
    scores = pd.Series({"A": -0.5, "B": -0.1, "C": 0.8, "D": 0.2})

    selected = select_topk(scores, k=3, guardrail=True)

    # Only C(0.8) and D(0.2) pass the score threshold
    assert selected == ["C", "D"]
    assert len(selected) < 3  # fewer than k returned


def test_select_topk_guardrail_filters_by_price_ma():
    """Guardrail price < MA filter is independent of score order."""
    scores = pd.Series({"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6})
    prices = pd.Series({"A": 95.0, "B": 105.0, "C": 98.0, "D": 110.0})
    ma = pd.Series({"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0})

    selected = select_topk(scores, k=2, guardrail=True, prices=prices, ma=ma)

    # B(105>=100), D(110>=100); A(95<100), C(98<100) rejected
    assert selected == ["B", "D"]
    assert len(selected) == 2


def test_select_topk_no_guardrail_returns_top_k():
    """guardrail=False returns top-k by score, regardless of sign or price."""
    scores = pd.Series({"A": -0.5, "B": 0.3, "C": -0.2, "D": 0.7})

    selected = select_topk(scores, k=2, guardrail=False)

    assert selected == ["D", "B"]


def test_select_bottomk_has_no_guardrail():
    scores = pd.Series({"A": -0.5, "B": 0.1, "C": -0.2})

    selected = select_bottomk(scores, k=2)

    assert selected == ["A", "C"]


# ---------------------------------------------------------------------------
# portfolio — build_rolling_portfolio
# ---------------------------------------------------------------------------


def test_build_rolling_portfolio_returns_result():
    """Returns RollingPortfolioResult with correct holdings and returns."""
    dates = pd.date_range("2024-01-02", periods=4, freq="D")
    instruments = ["A", "B", "C", "D"]
    midx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

    score_panel = pd.DataFrame(
        {
            "score": [
                0.9, 0.8, -0.1, 0.7,  # Jan 2
                0.1, 0.2, -0.3, 0.8,  # Jan 3
                -0.2, 0.3, -0.5, 0.4,  # Jan 4
                0.5, 0.4, -0.2, 0.1,  # Jan 5
            ]
        },
        index=midx,
    )

    return_panel = pd.DataFrame(
        {
            "return": [
                0.01, 0.03, 0.02, -0.01,  # Jan 2
                0.02, -0.01, 0.01, 0.015,  # Jan 3
                0.01, 0.005, -0.02, 0.02,  # Jan 4
                0.01, 0.00, -0.01, 0.01,  # Jan 5
            ]
        },
        index=midx,
    )

    result = build_rolling_portfolio(score_panel, return_panel, k=2, holding_days=2)

    # ── Type ──────────────────────────────────────────────────────────────
    assert isinstance(result, RollingPortfolioResult)

    # ── Holdings at rebalance dates (holding_days=2 → Jan 2, Jan 4) ──────
    assert result.long_holdings.get(pd.Timestamp("2024-01-02")) == ["A", "B"]
    assert result.short_holdings.get(pd.Timestamp("2024-01-02")) == ["C", "D"]
    assert result.long_holdings.get(pd.Timestamp("2024-01-04")) == ["D", "B"]
    assert result.short_holdings.get(pd.Timestamp("2024-01-04")) == ["C", "A"]

    # ── Equal-weight returns: Jan 2 (fresh rebalance) ────────────────────
    # long: (A=0.01 + B=0.03) / 2
    np.testing.assert_almost_equal(result.long_returns.iloc[0], 0.02)
    # short: (C=0.02 + D=-0.01) / 2
    np.testing.assert_almost_equal(result.short_returns.iloc[0], 0.005)
    # spread
    np.testing.assert_almost_equal(result.spread_returns.iloc[0], 0.015)

    # ── Hold-over: Jan 3 uses Jan 2 holdings ─────────────────────────────
    # long: (A=0.02 + B=-0.01) / 2
    np.testing.assert_almost_equal(result.long_returns.iloc[1], 0.005)
    # short: (C=0.01 + D=0.015) / 2
    np.testing.assert_almost_equal(result.short_returns.iloc[1], 0.0125)

    # ── Equity curves ──────────────────────────────────────────────────
    assert isinstance(result.long_equity, pd.Series)
    assert isinstance(result.spread_equity, pd.Series)
    assert len(result.long_equity) == 4
    # spread equity compounds: (1+0.015)*(1-0.0075) = 1.015 * 0.9925
    np.testing.assert_almost_equal(result.spread_equity.iloc[1], 1.0073875, decimal=5)


def test_build_rolling_portfolio_long_only():
    """long_only=True produces zero short returns and no short holdings."""
    dates = pd.date_range("2024-01-02", periods=2, freq="D")
    instruments = ["A", "B"]
    midx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

    score_panel = pd.DataFrame({"score": [0.9, 0.1, 0.8, -0.1]}, index=midx)
    return_panel = pd.DataFrame({"return": [0.01, 0.02, 0.03, 0.01]}, index=midx)

    result = build_rolling_portfolio(score_panel, return_panel, k=1, holding_days=1, long_only=True)

    # Short returns are zero (no short leg — code assigns 0.0 per day)
    assert (result.short_returns == 0.0).all()
    # Long returns have actual values
    assert result.long_returns.abs().sum() > 0


# ---------------------------------------------------------------------------
# metrics — compute_spread
# ---------------------------------------------------------------------------


def test_compute_spread_aligns_inputs():
    long_returns = pd.Series(
        [0.02, 0.01, -0.005],
        index=pd.date_range("2024-01-02", periods=3),
    )
    short_returns = pd.Series(
        [0.01, -0.02, 0.005],
        index=pd.date_range("2024-01-02", periods=3),
    )

    result = compute_spread(long_returns, short_returns)

    # Required keys
    for key in ("spread_mean", "spread_std", "spread_sharpe", "spread_series", "spread_equity"):
        assert key in result

    # spread = long - short (aligned)
    np.testing.assert_almost_equal(result["spread_series"].iloc[0], 0.01)  # 0.02 - 0.01
    np.testing.assert_almost_equal(result["spread_series"].iloc[1], 0.03)  # 0.01 - (-0.02)
    np.testing.assert_almost_equal(result["spread_series"].iloc[2], -0.01)  # -0.005 - 0.005

    # alpha fields are NaN when no benchmark
    assert np.isnan(result["alpha_long"])
    assert np.isnan(result["alpha_short"])

    # spread_mean
    np.testing.assert_almost_equal(result["spread_mean"], 0.01)

    # equity curve: (1 + spread_series).cumprod()
    expected_equity = (1 + result["spread_series"]).cumprod()
    pd.testing.assert_series_equal(result["spread_equity"], expected_equity)


def test_compute_spread_with_benchmark():
    long_returns = pd.Series(
        [0.02, 0.01],
        index=pd.date_range("2024-01-02", periods=2),
    )
    short_returns = pd.Series(
        [0.01, -0.02],
        index=pd.date_range("2024-01-02", periods=2),
    )
    bench_returns = pd.Series(
        [0.005, 0.01],
        index=pd.date_range("2024-01-02", periods=2),
    )

    result = compute_spread(long_returns, short_returns, bench_returns)

    # alpha_long = mean(long - bench) = mean([0.015, 0.0]) = 0.0075
    np.testing.assert_almost_equal(result["alpha_long"], 0.0075)
    # alpha_short = mean(bench - short) = mean([-0.005, 0.03]) = 0.0125
    np.testing.assert_almost_equal(result["alpha_short"], 0.0125)

    # spread is unaffected by benchmark presence
    np.testing.assert_almost_equal(result["spread_mean"], 0.02)


# ---------------------------------------------------------------------------
# metrics — compute_ic_series
# ---------------------------------------------------------------------------


def test_compute_ic_series_perfect_rank_correlation():
    """Spearman IC is 1.0 when score ranks perfectly predict return ranks."""
    dates = pd.date_range("2024-01-02", periods=3, freq="D")
    instruments = ["A", "B", "C", "D", "E"]
    midx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

    # Both score and return have identical monotonic rank order per date
    score_panel = pd.DataFrame(
        {"score": np.tile([0.9, 0.7, 0.1, -0.1, -0.3], 3)},
        index=midx,
    )
    return_panel = pd.DataFrame(
        {"return": np.tile([0.05, 0.03, -0.01, -0.02, -0.04], 3)},
        index=midx,
    )

    ic = compute_ic_series(score_panel, return_panel, min_stocks=3)

    assert ic["n_days"] == 3
    np.testing.assert_almost_equal(ic["ic_mean"], 1.0)
    assert ic["ic_pos_pct"] == 1.0  # every day positive


def test_compute_ic_series_insufficient_stocks():
    """IC not computed when fewer than min_stocks instruments."""
    dates = pd.date_range("2024-01-02", periods=2, freq="D")
    instruments = ["A", "B"]
    midx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

    score_panel = pd.DataFrame({"score": [0.9, 0.1, 0.8, -0.1]}, index=midx)
    return_panel = pd.DataFrame({"return": [0.05, -0.01, 0.03, 0.01]}, index=midx)

    ic = compute_ic_series(score_panel, return_panel, min_stocks=5)

    assert ic["n_days"] == 0
    assert np.isnan(ic["ic_mean"])
    assert np.isnan(ic["ic_std"])
    assert np.isnan(ic["ic_pos_pct"])
