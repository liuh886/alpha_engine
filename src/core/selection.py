"""Selection utilities for TopN/BottomN portfolio construction."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class GuardrailInputs:
    """Optional long-side guardrail inputs."""

    prices: pd.Series | None = None
    moving_average: pd.Series | None = None
    require_positive_score: bool = True


def _passes_long_guardrail(
    ticker: str,
    score: float,
    guardrail: GuardrailInputs | None,
) -> bool:
    if guardrail is None:
        return True

    if guardrail.require_positive_score and score <= 0:
        return False

    if guardrail.prices is None or guardrail.moving_average is None:
        return True

    if ticker not in guardrail.prices.index or ticker not in guardrail.moving_average.index:
        return False

    price = guardrail.prices.loc[ticker]
    moving_average = guardrail.moving_average.loc[ticker]
    if pd.isna(price) or pd.isna(moving_average):
        return False
    return bool(price > moving_average)


def select_topn(
    scores: pd.Series,
    n: int,
    guardrail: GuardrailInputs | None = None,
    buffer_multiplier: int = 3,
) -> list[str]:
    """Select top-N symbols with optional long-side guardrail filtering."""
    if n <= 0 or scores.empty:
        return []

    del buffer_multiplier  # Kept for backward-compatible call sites.
    ranked = scores.dropna().sort_values(ascending=False)
    selected: list[str] = []
    for ticker, score in ranked.items():
        if _passes_long_guardrail(str(ticker), float(score), guardrail):
            selected.append(str(ticker))
        if len(selected) >= n:
            break
    return selected


def select_bottomn(scores: pd.Series, n: int) -> list[str]:
    """Select bottom-N symbols with no guardrail filtering."""
    if n <= 0 or scores.empty:
        return []
    return [str(ticker) for ticker in scores.dropna().sort_values(ascending=True).head(n).index]
