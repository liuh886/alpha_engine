from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd


def apply_profile_universe_filters(
    instruments: Sequence[str],
    *,
    profile: dict | None,
    asof_time: str,
    fetch_features: Callable[..., pd.DataFrame] | None = None,
) -> list[str]:
    if not instruments:
        return []
    if not isinstance(profile, dict):
        return list(instruments)

    universe = profile.get("universe", {})
    if not isinstance(universe, dict):
        return list(instruments)

    filters = universe.get("filters", {})
    if not isinstance(filters, dict):
        return list(instruments)

    return filter_by_min_liquidity(
        instruments,
        asof_time=asof_time,
        min_liquidity=filters.get("min_liquidity"),
        fetch_features=fetch_features,
    )


def filter_by_min_liquidity(
    instruments: Sequence[str],
    *,
    asof_time: str,
    min_liquidity: float | int | None,
    fetch_features: Callable[..., pd.DataFrame] | None = None,
) -> list[str]:
    if not instruments:
        return []
    if min_liquidity is None:
        return list(instruments)

    if fetch_features is None:
        from qlib.data import D  # local import to keep optional dependency

        fetch_features = D.features

    fields = ["$close", "$volume"]
    df = fetch_features(instruments, fields, start_time=asof_time, end_time=asof_time)
    if df is None or len(df) == 0:
        return list(instruments)

    close = df.get(fields[0])
    volume = df.get(fields[1])
    if close is None or volume is None:
        return list(instruments)

    dollar_volume = close.astype(float) * volume.astype(float)
    if isinstance(dollar_volume, pd.DataFrame):
        dollar_volume = dollar_volume.iloc[:, 0]

    values_by_instrument = dollar_volume.groupby(level="instrument").last()

    eligible = {
        instrument
        for instrument, value in values_by_instrument.items()
        if pd.notna(value) and float(value) >= float(min_liquidity)
    }
    return [instrument for instrument in instruments if instrument in eligible]
