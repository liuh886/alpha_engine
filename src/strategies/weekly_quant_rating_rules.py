from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date


def select_top_fraction(items: Sequence[tuple[str, float]], strongbuy_fraction: float) -> set[str]:
    """
    Select the top fraction of items by score.
    items: sequence of (instrument, score) sorted or unsorted.
    Returns a set of instruments in the top fraction (at least 1 if items non-empty).
    """
    if not items:
        return set()
    frac = float(strongbuy_fraction)
    if frac <= 0:
        return set()
    if frac > 1:
        frac = 1.0

    sorted_items = sorted(items, key=lambda x: float(x[1]), reverse=True)
    k = int(round(len(sorted_items) * frac))
    k = max(1, min(len(sorted_items), k))
    return {inst for inst, _ in sorted_items[:k]}


def update_streaks(streaks: dict[str, int], strongbuy_today: Iterable[str]) -> dict[str, int]:
    """
    Update consecutive StrongBuy streaks.
    - If instrument is in strongbuy_today: increment streak
    - Else: reset to 0 (by deleting key)
    """
    today = set(str(x) for x in strongbuy_today)
    next_streaks: dict[str, int] = {}
    for inst in today:
        next_streaks[inst] = int(streaks.get(inst, 0)) + 1
    return next_streaks


def is_last_trading_day_of_week(current: date, next_trading_day: date | None) -> bool:
    """
    True if current trading day is the last trading day of its ISO week.
    If next_trading_day is None, treat current as last (end of data).
    """
    if next_trading_day is None:
        return True
    return current.isocalendar()[:2] != next_trading_day.isocalendar()[:2]


def select_target(
    *,
    scores_by_instrument: Mapping[str, float],
    streaks: Mapping[str, int],
    eligible_by_instrument: Mapping[str, bool],
    strongbuy_consecutive_days: int,
    universe_size: int,
) -> list[str]:
    """
    Select target instruments for the weekly rebalance:
    - must be eligible (filters)
    - must have strongbuy streak >= strongbuy_consecutive_days
    - sorted by score descending
    - capped to universe_size
    """
    min_streak = int(strongbuy_consecutive_days)
    if min_streak <= 0:
        min_streak = 1
    cap = int(universe_size)
    if cap <= 0:
        cap = 0

    candidates: list[tuple[str, float]] = []
    for inst, score in scores_by_instrument.items():
        if not eligible_by_instrument.get(inst, False):
            continue
        if int(streaks.get(inst, 0)) < min_streak:
            continue
        candidates.append((str(inst), float(score)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = [inst for inst, _ in candidates]
    if cap:
        selected = selected[:cap]
    return selected
