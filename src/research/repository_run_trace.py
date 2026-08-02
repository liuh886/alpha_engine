"""Retain exact non-overlapping portfolio traces for Repository Run evidence."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.research.portfolio_intent import (
    SignalFrame,
    evaluate_portfolio_intent,
    score_to_equal_weight_intent,
)


def _score_frame(value: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(value, pd.Series):
        frame = value.to_frame("score")
    else:
        frame = value.copy()
    if len(frame.columns) != 1:
        raise ValueError("candidate input must have exactly one score column")
    frame.columns = ["score"]
    return frame


def _aligned_inputs(
    scores: pd.DataFrame,
    raw_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    common = scores.index.intersection(raw_returns.index)
    if len(common) == 0:
        return scores.iloc[0:0], raw_returns.iloc[0:0]
    joined = pd.DataFrame(
        {
            "score": scores.loc[common, "score"].astype(float),
            "return": raw_returns.loc[common, "return"].astype(float),
        },
        index=common,
    ).replace([np.inf, -np.inf], np.nan)
    joined = joined.dropna()
    score_frame = joined[["score"]]
    return_frame = joined[["return"]]
    return_frame.attrs.update(raw_returns.attrs)
    return score_frame, return_frame


def _holdings(intent) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date in intent.rebalance_dates:
        weights = intent.weights_for(date)
        if weights is None:
            rows.append(
                {
                    "signal_date": str(date.date()),
                    "action": "hold_previous",
                    "weights": {},
                }
            )
        else:
            rows.append(
                {
                    "signal_date": str(date.date()),
                    "action": "rebalance",
                    "weights": dict(sorted(weights.items())),
                }
            )
    return rows


def _contributions(
    holdings: list[dict[str, Any]],
    raw_returns: pd.DataFrame,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in holdings:
        if row["action"] != "rebalance":
            continue
        date = pd.Timestamp(row["signal_date"])
        try:
            values = raw_returns.xs(date, level="datetime")["return"]
        except KeyError:
            continue
        contributions = {
            symbol: float(weight) * float(values.loc[symbol])
            for symbol, weight in row["weights"].items()
            if symbol in values.index and np.isfinite(float(values.loc[symbol]))
        }
        output.append(
            {
                "signal_date": row["signal_date"],
                "forward_horizon_sessions": int(raw_returns.attrs.get("horizon") or 10),
                "name_contributions": dict(sorted(contributions.items())),
                "gross_portfolio_return": float(sum(contributions.values())),
            }
        )
    return output


def build_candidate_backtest_traces(
    candidates: dict[str, pd.Series | pd.DataFrame],
    raw_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.DataFrame | None,
    top_n: int,
    rebalance_days: int,
    cost_bps: float = 20.0,
    benchmark: str = "",
    experiment_id: str = "",
) -> list[dict[str, Any]]:
    """Build exact period-NAV, holdings and contribution traces for candidates.

    These are non-overlapping forward-horizon traces. They are not described as
    daily NAV. Every point is tied to the signal/rebalance date consumed by the
    canonical fixed-horizon backtest.
    """

    traces: list[dict[str, Any]] = []
    for candidate_name, values in candidates.items():
        base = _score_frame(values)
        for orientation in ("original", "inverted"):
            oriented = base if orientation == "original" else -base
            scores, returns = _aligned_inputs(oriented, raw_returns)
            if scores.empty:
                continue
            dates = tuple(sorted(scores.index.get_level_values("datetime").unique()))
            signal = SignalFrame(
                scores=scores,
                research_contract_id=experiment_id,
                benchmark=benchmark,
                rebalance_days=rebalance_days,
                provenance={
                    "candidate_name": candidate_name,
                    "orientation": orientation,
                    "source": "spec_bound_fixed_horizon_backtest",
                },
            )
            intent = score_to_equal_weight_intent(
                signal,
                top_n=top_n,
                evaluation_dates=dates,
            )
            report = evaluate_portfolio_intent(
                intent,
                returns,
                benchmark_returns=benchmark_returns,
                cost_bps=cost_bps,
            )
            holding_rows = _holdings(intent)
            values_portfolio = list(report.portfolio_values)
            values_benchmark = list(report.benchmark_values)
            peak = values_portfolio[0]
            points: list[dict[str, Any]] = []
            for index, date in enumerate(intent.rebalance_dates):
                nav = values_portfolio[index + 1] / values_portfolio[0]
                benchmark_nav = values_benchmark[index + 1] / values_benchmark[0]
                peak = max(peak, values_portfolio[index + 1])
                points.append(
                    {
                        "signal_date": str(date.date()),
                        "nav_after_forward_horizon": nav,
                        "benchmark_nav_after_forward_horizon": benchmark_nav,
                        "drawdown": values_portfolio[index + 1] / peak - 1.0,
                        "net_period_return": report.period_returns[index],
                    }
                )
            traces.append(
                {
                    "schema_version": "1.0.0",
                    "candidate_name": candidate_name,
                    "orientation": orientation,
                    "trace_frequency": "non_overlapping_forward_horizon",
                    "value_semantics": "value_after_return_beginning_on_signal_date",
                    "forward_horizon_sessions": int(raw_returns.attrs.get("horizon") or 10),
                    "top_n": top_n,
                    "rebalance_days": rebalance_days,
                    "cost_bps": cost_bps,
                    "points": points,
                    "holdings": holding_rows,
                    "name_contributions": _contributions(holding_rows, returns),
                    "metrics": report.to_dict(),
                    "research_only": True,
                    "trade_ready": False,
                }
            )
    return traces
