"""Performance metrics for spread and benchmark-relative evaluation."""

from __future__ import annotations

import pandas as pd


def compute_spread_metrics(
    long_returns: pd.Series,
    short_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
) -> dict[str, object]:
    """Compute spread and benchmark-relative summary metrics."""
    returns = pd.concat(
        [
            long_returns.rename("long"),
            short_returns.rename("short"),
        ],
        axis=1,
    ).fillna(0.0)
    spread_series = (returns["long"] - returns["short"]).rename("spread")

    result: dict[str, object] = {
        "spread_mean": float(spread_series.mean()),
        "spread_std": float(spread_series.std(ddof=0)),
        "spread_cum_return": float((1.0 + spread_series).prod() - 1.0),
        "spread_series": spread_series,
    }

    if benchmark_returns is not None:
        aligned = pd.concat(
            [
                returns["long"],
                returns["short"],
                benchmark_returns.rename("benchmark"),
            ],
            axis=1,
        ).fillna(0.0)
        alpha_long = (aligned["long"] - aligned["benchmark"]).rename("alpha_long")
        alpha_short = (aligned["benchmark"] - aligned["short"]).rename("alpha_short")
        result.update(
            {
                "alpha_long_mean": float(alpha_long.mean()),
                "alpha_short_mean": float(alpha_short.mean()),
                "alpha_long_cum_return": float((1.0 + alpha_long).prod() - 1.0),
                "alpha_short_cum_return": float((1.0 + alpha_short).prod() - 1.0),
                "alpha_long_series": alpha_long,
                "alpha_short_series": alpha_short,
            }
        )

    return result
