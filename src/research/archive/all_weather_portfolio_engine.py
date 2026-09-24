"""Portfolio engine for All Weather Multi Asset Alpha Rotation.

Implements the first executable layer: signal score aggregation, target weights,
next-session execution convention and cost-aware NAV simulation.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


class AllWeatherPortfolioError(ValueError):
    pass


def momentum_score(prices: pd.DataFrame) -> pd.Series:
    """Simple governed momentum score from available close history."""
    if len(prices) < 20:
        raise AllWeatherPortfolioError("need at least 20 observations")
    ret20 = prices.iloc[-1] / prices.iloc[-21] - 1
    ret60 = prices.iloc[-1] / prices.iloc[-61] - 1 if len(prices) >= 61 else ret20
    return (ret20 * 0.5 + ret60 * 0.5).rank(pct=True)


def build_target_weights(
    prices: pd.DataFrame,
    *,
    cash_symbol: str = "515180",
    max_assets: int = 5,
    active_exposure: float = 0.8,
) -> pd.Series:
    """Create transparent equal-weight rotation allocation."""
    score = momentum_score(prices)
    selected = score.sort_values(ascending=False).head(max_assets)
    weights = pd.Series(0.0, index=prices.columns)
    if len(selected):
        weights.loc[selected.index] = active_exposure / len(selected)
    if cash_symbol in weights.index:
        weights.loc[cash_symbol] = 1.0 - weights.sum()
    return weights


def simulate_portfolio(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    cost_bps: float = 20.0,
) -> dict[str, Any]:
    """Run daily weight simulation with turnover cost."""
    returns = prices.pct_change().fillna(0.0)
    held = weights.shift(1).fillna(0.0)
    gross = (held * returns).sum(axis=1)
    turnover = held.diff().abs().sum(axis=1).fillna(held.abs().sum(axis=1))
    cost = turnover * cost_bps / 10000.0
    net = gross - cost
    nav = (1 + net).cumprod()
    return {
        "nav": nav,
        "daily_return": net,
        "turnover": turnover,
        "transaction_cost": cost,
        "metrics": {
            "total_return": float(nav.iloc[-1] - 1),
            "max_drawdown": float((nav / nav.cummax() - 1).min()),
        },
    }
