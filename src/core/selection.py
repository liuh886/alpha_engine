"""Stock selection — pure functions.

All functions accept a ``pd.Series`` of scores (index = instrument ticker)
and return a plain ``list`` of selected tickers.  No I/O, no state.
"""
from __future__ import annotations

import pandas as pd
from typing import Optional


def select_topk(
    scores: pd.Series,
    k: int,
    guardrail: bool = True,
    prices: Optional[pd.Series] = None,
    ma: Optional[pd.Series] = None,
    min_score: float = 0.0,
    candidate_multiplier: int = 3,
) -> list[str]:
    """Select top-K tickers by score with an optional guardrail filter.

    The guardrail rejects tickers where *either* of the following is true:
      - score <= ``min_score``  (typically 0, filtering negative expected-return signals)
      - ``prices[ticker] < ma[ticker]``  (price below its moving average)

    When ``guardrail=True`` but ``prices`` or ``ma`` is None, only the
    score threshold filter is applied.

    Parameters
    ----------
    scores:
        Cross-sectional scores, index = ticker symbol.
    k:
        Target number of tickers to return.
    guardrail:
        Enable guardrail filtering (default True).
    prices:
        Latest closing prices keyed by ticker.
    ma:
        Moving-average prices keyed by ticker (e.g. MA60).
    min_score:
        Minimum score threshold for the guardrail (default 0.0).
    candidate_multiplier:
        How many extra candidates to pre-screen before applying the guardrail
        (default 3 × k, so up to 3k candidates are evaluated).

    Returns
    -------
    list[str]
        Up to ``k`` ticker symbols, ordered by descending score.

    Examples
    --------
    >>> top10 = select_topk(scores, k=10, guardrail=True, prices=close_ser, ma=ma60_ser)
    >>> top10_no_guard = select_topk(scores, k=10, guardrail=False)
    """
    # Pre-screen: take k * multiplier candidates so guardrail has room to reject
    candidates = scores.nlargest(k * candidate_multiplier)

    if not guardrail:
        return candidates.index[:k].tolist()

    selected: list[str] = []
    for ticker in candidates.index:
        if len(selected) >= k:
            break

        # Score threshold
        if candidates[ticker] <= min_score:
            continue

        # Price vs MA filter (only when both series provided)
        if prices is not None and ma is not None:
            price = prices.get(ticker) if hasattr(prices, "get") else prices.get(ticker, None)
            moving_avg = ma.get(ticker) if hasattr(ma, "get") else ma.get(ticker, None)
            if price is not None and moving_avg is not None:
                if price < moving_avg:
                    continue

        selected.append(ticker)

    return selected


def select_bottomk(
    scores: pd.Series,
    k: int,
) -> list[str]:
    """Select bottom-K tickers by score — **no guardrail applied**.

    BottomN represents the short leg of a long-short strategy.  No guardrail
    is applied because we *want* the weakest names, including negative-score ones.

    Parameters
    ----------
    scores:
        Cross-sectional scores, index = ticker symbol.
    k:
        Number of tickers to return.

    Returns
    -------
    list[str]
        Exactly ``k`` ticker symbols, ordered by ascending score.

    Examples
    --------
    >>> bot10 = select_bottomk(scores, k=10)
    """
    return scores.nsmallest(k).index.tolist()


def select_topk_bottomk(
    scores: pd.Series,
    k_long: int,
    k_short: int,
    guardrail: bool = True,
    prices: Optional[pd.Series] = None,
    ma: Optional[pd.Series] = None,
) -> dict[str, list[str]]:
    """Convenience wrapper: select both long and short legs in one call.

    Returns
    -------
    dict with keys ``"long"`` and ``"short"``.

    Examples
    --------
    >>> portfolio = select_topk_bottomk(scores, k_long=10, k_short=10)
    >>> portfolio["long"], portfolio["short"]
    """
    return {
        "long": select_topk(scores, k_long, guardrail=guardrail, prices=prices, ma=ma),
        "short": select_bottomk(scores, k_short),
    }
