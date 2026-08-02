"""Diagnostics for the promoted v4.2 research baseline.

This module does not change signals or portfolio weights. It decomposes state-1
lifecycles and measures tail risk so later challengers can be evaluated against
v4.2 without relying on headline CAGR alone.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult


def _path_statistics(returns: pd.Series) -> dict[str, float | int]:
    clean = returns.dropna().astype(float)
    if clean.empty:
        return {
            "sessions": 0,
            "cumulative_return": 0.0,
            "mean_daily_return": 0.0,
            "positive_session_rate": 0.0,
            "max_drawdown": 0.0,
            "maximum_favourable_excursion": 0.0,
            "maximum_adverse_excursion": 0.0,
        }
    equity = (1.0 + clean).cumprod()
    anchored = pd.concat([pd.Series([1.0]), equity.reset_index(drop=True)], ignore_index=True)
    drawdown = anchored / anchored.cummax() - 1.0
    return {
        "sessions": int(len(clean)),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "mean_daily_return": float(clean.mean()),
        "positive_session_rate": float(clean.gt(0.0).mean()),
        "max_drawdown": float(drawdown.min()),
        "maximum_favourable_excursion": float(anchored.max() - 1.0),
        "maximum_adverse_excursion": float(anchored.min() - 1.0),
    }


def state_one_lifecycle_attribution(
    v4_1: StrategyResult,
    v4_2: StrategyResult,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Describe every contiguous state-1 interval and compare v4.2 with v4.1."""

    left = v4_1.daily
    right = v4_2.daily
    common = left.index.intersection(right.index)
    if not left.loc[common, "position_state"].equals(right.loc[common, "position_state"]):
        raise AssertionError("v4.1 and v4.2 state traces must be identical")

    states = right.loc[common, "position_state"].astype(int)
    starts = states.eq(1) & states.shift(1).ne(1)
    rows: list[dict[str, Any]] = []
    for start_date in states.index[starts]:
        start_location = states.index.get_loc(start_date)
        end_location = start_location
        while end_location + 1 < len(states) and int(states.iloc[end_location + 1]) == 1:
            end_location += 1
        end_date = states.index[end_location]
        previous_state = int(states.iloc[start_location - 1]) if start_location > 0 else -1
        next_state = int(states.iloc[end_location + 1]) if end_location + 1 < len(states) else -1
        lifecycle = f"{previous_state}->1->{next_state}"
        row: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "previous_state": previous_state,
            "next_state": next_state,
            "lifecycle": lifecycle,
        }
        for label, result in (("v4_1", v4_1), ("v4_2", v4_2)):
            interval = result.daily.loc[start_date:end_date]
            gross = _path_statistics(interval["gross_return"])
            net = _path_statistics(interval["net_return"])
            row.update(
                {
                    f"{label}_sessions": net["sessions"],
                    f"{label}_gross_return": gross["cumulative_return"],
                    f"{label}_net_return": net["cumulative_return"],
                    f"{label}_max_drawdown": net["max_drawdown"],
                    f"{label}_mfe": net["maximum_favourable_excursion"],
                    f"{label}_mae": net["maximum_adverse_excursion"],
                    f"{label}_turnover_units": float(interval["turnover_units"].sum()),
                    f"{label}_transaction_cost": float(interval["transaction_cost"].sum()),
                }
            )
        row["net_return_delta"] = row["v4_2_net_return"] - row["v4_1_net_return"]
        row["max_drawdown_improvement"] = row["v4_2_max_drawdown"] - row["v4_1_max_drawdown"]
        row["turnover_saved"] = row["v4_1_turnover_units"] - row["v4_2_turnover_units"]
        row["cost_saved"] = row["v4_1_transaction_cost"] - row["v4_2_transaction_cost"]
        rows.append(row)

    episodes = pd.DataFrame(rows)
    if episodes.empty:
        return episodes, pd.DataFrame()
    summary = (
        episodes.groupby("lifecycle", dropna=False)
        .agg(
            episodes=("lifecycle", "size"),
            mean_sessions=("v4_2_sessions", "mean"),
            mean_v4_1_net_return=("v4_1_net_return", "mean"),
            mean_v4_2_net_return=("v4_2_net_return", "mean"),
            mean_net_return_delta=("net_return_delta", "mean"),
            positive_delta_rate=("net_return_delta", lambda values: float((values > 0).mean())),
            mean_drawdown_improvement=("max_drawdown_improvement", "mean"),
            total_turnover_saved=("turnover_saved", "sum"),
            total_cost_saved=("cost_saved", "sum"),
        )
        .reset_index()
    )
    return episodes, summary


def _longest_underwater_run(drawdown: pd.Series) -> int:
    underwater = drawdown.lt(-1e-12)
    if not underwater.any():
        return 0
    groups = underwater.ne(underwater.shift()).cumsum()
    return int(underwater.groupby(groups).sum().max())


def tail_risk_metrics(result: StrategyResult) -> dict[str, Any]:
    """Return tail, drawdown-depth and drawdown-duration diagnostics."""

    returns = result.daily["net_return"].dropna().astype(float)
    if returns.empty:
        raise ValueError("strategy result has no returns")
    equity = (1.0 + returns).cumprod()
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    quantile_05 = float(returns.quantile(0.05))
    expected_shortfall_95 = float(returns.loc[returns.le(quantile_05)].mean())

    rolling: dict[str, float | None] = {}
    for horizon in (5, 10, 20):
        compounded = (1.0 + returns).rolling(horizon).apply(np.prod, raw=True) - 1.0
        rolling[f"worst_{horizon}d_return"] = (
            float(compounded.min()) if compounded.notna().any() else None
        )

    trough_date = drawdown.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    recovery = equity.loc[trough_date:]
    recovered = recovery.loc[recovery.ge(float(equity.loc[peak_date]))]
    recovery_date = recovered.index[0] if len(recovered) else None
    recovery_sessions = (
        int(returns.index.get_loc(recovery_date) - returns.index.get_loc(peak_date))
        if recovery_date is not None
        else None
    )
    state_tail: dict[str, Any] = {}
    if "position_state" in result.daily.columns:
        aligned_states = result.daily.loc[returns.index, "position_state"].astype(int)
        for state in (0, 1, 2):
            sample = returns.loc[aligned_states.eq(state)]
            state_tail[str(state)] = {
                "sessions": int(len(sample)),
                "mean_daily_return": float(sample.mean()) if len(sample) else None,
                "worst_daily_return": float(sample.min()) if len(sample) else None,
                "negative_session_rate": float(sample.lt(0).mean()) if len(sample) else None,
            }

    return {
        "strategy": str(result.metrics["strategy"]),
        "observations": int(len(returns)),
        "worst_daily_return": float(returns.min()),
        "daily_return_05_quantile": quantile_05,
        "expected_shortfall_95": expected_shortfall_95,
        **rolling,
        "max_drawdown": float(drawdown.min()),
        "max_drawdown_peak_date": peak_date.date().isoformat(),
        "max_drawdown_trough_date": trough_date.date().isoformat(),
        "max_drawdown_recovery_date": (
            recovery_date.date().isoformat() if recovery_date is not None else None
        ),
        "max_drawdown_recovery_sessions": recovery_sessions,
        "maximum_underwater_run_sessions": _longest_underwater_run(drawdown),
        "ulcer_index": float(np.sqrt(np.mean(np.square(drawdown.to_numpy(dtype=float))))),
        "state_tail": state_tail,
    }


def compare_tail_risk(results: Mapping[str, StrategyResult]) -> pd.DataFrame:
    rows = []
    for key, result in results.items():
        row = tail_risk_metrics(result)
        row["result_key"] = key
        row.pop("state_tail")
        rows.append(row)
    return pd.DataFrame(rows).set_index("result_key").sort_index()
