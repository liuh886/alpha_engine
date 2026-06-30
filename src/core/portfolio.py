"""Portfolio construction helpers for fixed and rolling holding windows."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class SleeveEntry:
    date: pd.Timestamp
    symbols: list[str]
    weight: float


def build_fixed_rebalance_schedule(trading_days: list[pd.Timestamp], holding_days: int) -> list[pd.Timestamp]:
    if holding_days <= 0:
        raise ValueError("holding_days must be positive")
    return list(trading_days[::holding_days])


def build_rolling_portfolio(
    signal_by_date: dict[pd.Timestamp, list[str]],
    holding_days: int = 10,
    sleeve_weight: float | None = None,
) -> pd.DataFrame:
    """Build rolling holdings where each daily signal forms one sleeve."""
    if holding_days <= 0:
        raise ValueError("holding_days must be positive")
    if sleeve_weight is None:
        sleeve_weight = 1.0 / holding_days

    active: deque[SleeveEntry] = deque()
    rows: list[dict[str, object]] = []

    for date in sorted(signal_by_date.keys()):
        active.append(SleeveEntry(date=date, symbols=signal_by_date[date], weight=sleeve_weight))
        while len(active) > holding_days:
            active.popleft()

        weights = defaultdict(float)
        for sleeve in active:
            if not sleeve.symbols:
                continue
            per_symbol_weight = sleeve.weight / len(sleeve.symbols)
            for symbol in sleeve.symbols:
                weights[symbol] += per_symbol_weight

        rows.append(
            {
                "date": date,
                "symbols": sorted(weights.keys()),
                "weights": dict(sorted(weights.items())),
                "gross_weight": float(sum(weights.values())),
                "num_names": int(len(weights)),
            }
        )

    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
