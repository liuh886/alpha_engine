"""Deterministic Phase 2 portfolio evidence for v4.23."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import (
    StrategyResult,
    _normalise_bars,
    _return_metrics,
)
from src.research.v4_23_xgb_lambdarank_data import (
    ACTION_WEIGHTS,
    action_asset_returns,
)
from src.research.v4_23_xgb_lambdarank_model import concentration_metrics


def strategy_daily(
    selected: pd.DataFrame,
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
    *,
    cash_symbol: str,
    strategy_name: str,
    fixed_action: str | None = None,
) -> StrategyResult:
    if selected.empty:
        return StrategyResult(strategy_name, pd.DataFrame(), pd.DataFrame(), {})
    index = _normalise_bars(bars["QQQ"], "QQQ").index
    returns = action_asset_returns(bars, index, cash_symbol=cash_symbol)
    sessions = int(contract["decision"]["holding_sessions"])
    cost_rate = (
        float(contract["decision"]["transaction_cost_bps_per_turnover_unit"])
        / 10_000.0
    )
    daily_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    previous = np.zeros(3, dtype=float)
    for block_number, block in enumerate(
        selected.sort_values("decision_date").itertuples(index=False)
    ):
        action = fixed_action or str(block.action)
        weights = np.asarray(ACTION_WEIGHTS[action], dtype=float)
        location = int(index.get_indexer([pd.Timestamp(block.decision_date)])[0])
        if location < 0 or location + 1 + sessions > len(index):
            continue
        turnover = float(np.abs(weights - previous).sum())
        for offset in range(sessions):
            date = pd.Timestamp(index[location + 1 + offset])
            asset = returns.loc[date]
            gross = float(
                weights[0] * asset["cash_return"]
                + weights[1] * asset["qqq_return"]
                + weights[2] * asset["tqqq_return"]
            )
            cost = turnover * cost_rate if offset == 0 else 0.0
            daily_rows.append(
                {
                    "date": date,
                    "block_number": block_number,
                    "decision_date": pd.Timestamp(block.decision_date),
                    "action": action,
                    "weight_cash": weights[0],
                    "weight_QQQ": weights[1],
                    "weight_TQQQ": weights[2],
                    "gross_return": gross,
                    "turnover_units": turnover if offset == 0 else 0.0,
                    "transaction_cost": cost,
                    "net_return": gross - cost,
                }
            )
        trade_rows.append(
            {
                "decision_date": pd.Timestamp(block.decision_date),
                "execution_date": pd.Timestamp(index[location + 1]),
                "from_cash": previous[0],
                "from_QQQ": previous[1],
                "from_TQQQ": previous[2],
                "to_action": action,
                "to_cash": weights[0],
                "to_QQQ": weights[1],
                "to_TQQQ": weights[2],
                "turnover_units": turnover,
                "cost": turnover * cost_rate,
            }
        )
        previous = weights
    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(trade_rows)
    if daily.empty:
        return StrategyResult(strategy_name, daily, trades, {})
    daily = daily.drop_duplicates("date", keep="first").set_index("date").sort_index()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"].div(daily["equity"].cummax()).sub(1.0)
    metrics = _return_metrics(daily["net_return"])
    metrics.update(
        {
            "strategy": strategy_name,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
        }
    )
    return StrategyResult(strategy_name, daily, trades, metrics)


def baseline_result(
    baseline_daily: pd.DataFrame,
    selected: pd.DataFrame,
    strategy_name: str,
    *,
    sessions: int,
) -> StrategyResult:
    if selected.empty:
        return StrategyResult(strategy_name, pd.DataFrame(), pd.DataFrame(), {})
    index = pd.DatetimeIndex(baseline_daily.index)
    dates: list[pd.Timestamp] = []
    for date in pd.to_datetime(selected["decision_date"]):
        location = int(index.get_indexer([date])[0])
        if location >= 0:
            dates.extend(index[location + 1 : location + 1 + sessions])
    daily = baseline_daily.reindex(sorted(set(dates))).dropna(subset=["net_return"])
    metrics = _return_metrics(daily["net_return"])
    turnover = (
        pd.to_numeric(daily["turnover_units"], errors="coerce").fillna(0.0).sum()
        if "turnover_units" in daily
        else 0.0
    )
    cost = (
        pd.to_numeric(daily["transaction_cost"], errors="coerce").fillna(0.0).sum()
        if "transaction_cost" in daily
        else 0.0
    )
    metrics.update(
        {
            "strategy": strategy_name,
            "turnover_units": float(turnover),
            "transaction_cost_paid": float(cost),
        }
    )
    return StrategyResult(strategy_name, daily, pd.DataFrame(), metrics)


def phase2_evidence(
    selected: pd.DataFrame,
    bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    actual: bool,
) -> tuple[
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, StrategyResult],
]:
    cash_symbol = "SGOV" if actual else "BIL"
    sessions = int(contract["decision"]["holding_sessions"])
    results = {
        "v4_2": baseline_result(
            baseline_daily, selected, "frozen_v4_2", sessions=sessions
        ),
        "xgb_state_machine": strategy_daily(
            selected,
            bars,
            contract,
            cash_symbol=cash_symbol,
            strategy_name="xgb_state_machine",
        ),
        "defense_only": strategy_daily(
            selected,
            bars,
            contract,
            cash_symbol=cash_symbol,
            strategy_name="defense_only",
            fixed_action="defense",
        ),
        "leveraged_only": strategy_daily(
            selected,
            bars,
            contract,
            cash_symbol=cash_symbol,
            strategy_name="leveraged_only",
            fixed_action="leveraged",
        ),
        "accelerated_only": strategy_daily(
            selected,
            bars,
            contract,
            cash_symbol=cash_symbol,
            strategy_name="accelerated_only",
            fixed_action="accelerated",
        ),
    }
    headline = pd.DataFrame(
        [{"strategy_key": key, **result.metrics} for key, result in results.items()]
    ).set_index("strategy_key")
    return (
        headline,
        {key: result.daily for key, result in results.items()},
        {key: result.trades for key, result in results.items()},
        results,
    )


def _annual_relative(candidate: StrategyResult, baseline: StrategyResult) -> pd.Series:
    aligned = pd.concat(
        [
            candidate.daily["net_return"].rename("candidate"),
            baseline.daily["net_return"].rename("baseline"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    rows: dict[int, float] = {}
    for year, table in aligned.groupby(aligned.index.year):
        rows[int(year)] = float(
            (1.0 + table["candidate"]).prod()
            - (1.0 + table["baseline"]).prod()
        )
    return pd.Series(rows, dtype=float)


def phase2_gate(
    headline: pd.DataFrame,
    results: Mapping[str, StrategyResult],
    selected: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    gate = contract["validation"]["phase2"]
    baseline = headline.loc["v4_2"]
    candidate = headline.loc["xgb_state_machine"]
    annual = _annual_relative(results["xgb_state_machine"], results["v4_2"])
    baseline_turnover = float(baseline["turnover_units"])
    turnover_increase = (
        float(candidate["turnover_units"] / baseline_turnover - 1.0)
        if baseline_turnover > 1e-12
        else np.inf
    )
    contribution = (
        selected.assign(
            positive=selected["realized_advantage_vs_v4_2"].clip(lower=0.0)
        )
        .groupby("action")["positive"]
        .sum()
    )
    total_positive = float(contribution.sum())
    largest_action_share = (
        float(contribution.max() / total_positive) if total_positive > 0 else np.nan
    )
    concentration = concentration_metrics(selected, contract).iloc[0]
    checks = {
        "cagr": float(candidate["cagr"] - baseline["cagr"])
        >= float(gate["cagr_improvement_pp_min"]) / 100.0,
        "max_drawdown": float(
            abs(candidate["max_drawdown"]) - abs(baseline["max_drawdown"])
        )
        <= float(gate["max_drawdown_worsening_pp_max"]) / 100.0,
        "calmar": float(candidate["calmar"] - baseline["calmar"])
        >= float(gate["calmar_improvement_min"]),
        "sortino": float(candidate["sortino"]) >= float(baseline["sortino"]),
        "positive_years": int(annual.gt(0.0).sum())
        >= int(gate["positive_calendar_years_min"]),
        "turnover": turnover_increase <= float(gate["turnover_increase_max"]),
        "without_best_year": float(concentration["advantage_without_best_year"])
        > 0.0,
        "without_best_cluster": float(
            concentration["advantage_without_best_cluster"]
        )
        > 0.0,
        "action_concentration": largest_action_share
        <= float(gate["largest_action_positive_share_max"]),
        "beats_ablations": all(
            float(candidate["cagr"]) > float(headline.loc[key, "cagr"])
            and float(candidate["calmar"]) > float(headline.loc[key, "calmar"])
            for key in ("defense_only", "leveraged_only", "accelerated_only")
        ),
    }
    return {
        "passed": bool(all(checks.values())),
        "skipped": False,
        "checks": checks,
        "cagr_delta_pp": float(candidate["cagr"] - baseline["cagr"]) * 100.0,
        "max_drawdown_worsening_pp": float(
            abs(candidate["max_drawdown"]) - abs(baseline["max_drawdown"])
        )
        * 100.0,
        "calmar_delta": float(candidate["calmar"] - baseline["calmar"]),
        "sortino_delta": float(candidate["sortino"] - baseline["sortino"]),
        "positive_calendar_years": int(annual.gt(0.0).sum()),
        "turnover_increase": turnover_increase,
        "largest_action_positive_share": largest_action_share,
    }


def actual_gate(headline: pd.DataFrame, contract: Mapping[str, Any]) -> dict[str, Any]:
    gate = contract["validation"]["actual"]
    baseline = headline.loc["v4_2"]
    candidate = headline.loc["xgb_state_machine"]
    both_trail = bool(
        float(candidate["cagr"]) < float(baseline["cagr"])
        and float(candidate["calmar"]) < float(baseline["calmar"])
    )
    worsening = float(
        abs(candidate["max_drawdown"]) - abs(baseline["max_drawdown"])
    ) * 100.0
    checks = {
        "not_both_cagr_and_calmar_trail": not both_trail,
        "max_drawdown": worsening
        <= float(gate["max_drawdown_worsening_pp_max"]),
    }
    return {
        "passed": bool(all(checks.values())),
        "skipped": False,
        "checks": checks,
        "cagr_delta_pp": float(candidate["cagr"] - baseline["cagr"]) * 100.0,
        "calmar_delta": float(candidate["calmar"] - baseline["calmar"]),
        "max_drawdown_worsening_pp": worsening,
    }
