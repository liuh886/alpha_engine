"""Governed verification of the BYD SMA25/70 breakout ATR claim.

The supplied rule is evaluated on the immutable BYD canonical v1 snapshot.
A same-close claimant diagnostic is retained, but only next-eligible-open
execution can support a research conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.research.byd_v1_2_recovery_state import (
    EVALUATION_WINDOWS,
    StrategyResult,
    build_research_dataset,
    build_v1_0_decision_position,
    run_buy_and_hold,
    run_strategy,
)

PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
BREAKOUT_WINDOW = 55
ATR_WINDOW = 14


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    core_position: float
    atr_multiple: float
    exit_confirmation_days: int
    complexity_rank: int


CANDIDATES = (
    CandidateSpec("claimant_flat_atr32", 0.00, 3.2, 1, 1),
    CandidateSpec("claimant_core50_atr32", 0.50, 3.2, 1, 2),
    CandidateSpec("claimant_core75_atr32", 0.75, 3.2, 1, 3),
    CandidateSpec("claimant_core75_atr36", 0.75, 3.6, 1, 4),
    CandidateSpec("claimant_core75_confirm2_atr32", 0.75, 3.2, 2, 5),
)


@dataclass(frozen=True)
class DecisionSchedule:
    candidate: CandidateSpec
    daily: pd.DataFrame


def add_claim_features(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = dataset.copy(deep=True)
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    previous_close = close.shift(1)

    frame["sma_25"] = close.rolling(25, min_periods=25).mean()
    frame["sma_70"] = close.rolling(70, min_periods=70).mean()
    frame["prior_high_55"] = (
        close.shift(1).rolling(BREAKOUT_WINDOW, min_periods=BREAKOUT_WINDOW).max()
    )
    frame["trend_bull"] = frame["sma_25"].gt(frame["sma_70"]) & close.gt(
        frame["sma_70"]
    )
    frame["breakout"] = close.gt(frame["prior_high_55"])
    frame["entry_condition"] = frame["trend_bull"] | (
        frame["breakout"] & frame["sma_25"].gt(frame["sma_70"] * 0.98)
    )

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr_14_wilder"] = true_range.ewm(
        alpha=1.0 / ATR_WINDOW,
        adjust=False,
        min_periods=ATR_WINDOW,
    ).mean()
    return frame


def build_candidate_schedule(
    dataset: pd.DataFrame,
    spec: CandidateSpec,
) -> DecisionSchedule:
    active = False
    highest_close = float("nan")
    exit_streak = 0

    positions: list[float] = []
    highest_values: list[float] = []
    stop_values: list[float] = []
    entry_signals: list[bool] = []
    exit_signals: list[bool] = []
    reasons: list[str] = []
    raw_exit_values: list[bool] = []

    for row in dataset.itertuples():
        close = float(row.close)
        atr = (
            float(row.atr_14_wilder)
            if pd.notna(row.atr_14_wilder)
            else float("nan")
        )
        entry_now = (
            bool(row.entry_condition) if pd.notna(row.entry_condition) else False
        )
        reason = ""
        entry_signal = False
        exit_signal = False
        raw_exit = False
        trailing_stop = float("nan")

        if not active:
            exit_streak = 0
            highest_close = float("nan")
            if entry_now and np.isfinite(atr):
                active = True
                highest_close = close
                trailing_stop = highest_close - spec.atr_multiple * atr
                entry_signal = True
                reason = "trend_bull" if bool(row.trend_bull) else "breakout"
        else:
            highest_close = max(highest_close, close)
            trailing_stop = highest_close - spec.atr_multiple * atr
            stop_breach = np.isfinite(trailing_stop) and close < trailing_stop
            death_cross = (
                pd.notna(row.sma_25)
                and pd.notna(row.sma_70)
                and float(row.sma_25) < float(row.sma_70)
                and close < float(row.sma_70)
            )
            raw_exit = bool(stop_breach or death_cross)
            exit_streak = exit_streak + 1 if raw_exit else 0
            if exit_streak >= spec.exit_confirmation_days:
                active = False
                exit_signal = True
                if stop_breach and death_cross:
                    reason = "trailing_stop_and_death_cross"
                elif stop_breach:
                    reason = "trailing_stop"
                else:
                    reason = "death_cross_below_sma70"
                exit_streak = 0

        positions.append(1.0 if active else spec.core_position)
        highest_values.append(highest_close if np.isfinite(highest_close) else np.nan)
        stop_values.append(trailing_stop)
        entry_signals.append(entry_signal)
        exit_signals.append(exit_signal)
        reasons.append(reason)
        raw_exit_values.append(raw_exit)

    daily = pd.DataFrame(
        {
            "decision_position": positions,
            "highest_close_since_entry": highest_values,
            "trailing_stop": stop_values,
            "entry_signal": entry_signals,
            "exit_signal": exit_signals,
            "raw_exit_condition": raw_exit_values,
            "signal_reason": reasons,
            "trend_bull": dataset["trend_bull"].astype(bool),
            "breakout": dataset["breakout"].astype(bool),
            "entry_condition": dataset["entry_condition"].astype(bool),
            "sma_25": dataset["sma_25"],
            "sma_70": dataset["sma_70"],
            "prior_high_55": dataset["prior_high_55"],
            "atr_14_wilder": dataset["atr_14_wilder"],
        },
        index=dataset.index,
    )
    allowed = {spec.core_position, 1.0}
    if not set(daily["decision_position"].unique()).issubset(allowed):
        raise AssertionError(f"{spec.name} produced undeclared positions")
    return DecisionSchedule(candidate=spec, daily=daily)


def run_candidate(
    dataset: pd.DataFrame,
    schedule: DecisionSchedule,
    *,
    cost_bps: float,
) -> StrategyResult:
    return run_strategy(
        dataset,
        schedule.daily["decision_position"],
        name=schedule.candidate.name,
        cost_bps_per_turnover_unit=cost_bps,
        initial_position=schedule.candidate.core_position,
    )


def run_same_close_diagnostic(
    dataset: pd.DataFrame,
    schedule: DecisionSchedule,
    *,
    cost_bps: float,
) -> StrategyResult:
    position = schedule.daily["decision_position"].astype(float)
    close_to_next = dataset["close"].shift(-1) / dataset["close"] - 1.0
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]) - schedule.candidate.core_position)
    cost = turnover * cost_bps / 10_000.0
    daily = pd.DataFrame(
        {
            "close": dataset["close"],
            "decision_position": position,
            "position_at_close": position,
            "gross_return": position * close_to_next,
            "turnover_units": turnover,
            "cost": cost,
        },
        index=dataset.index,
    )
    daily["net_return"] = daily["gross_return"] - daily["cost"]
    daily = daily.iloc[:-1].copy()
    changes = daily["position_at_close"].ne(daily["position_at_close"].shift(1))
    trades = daily.loc[
        changes,
        ["position_at_close", "turnover_units", "cost"],
    ].copy()
    trades["prior_position"] = daily["position_at_close"].shift(1).loc[trades.index]
    trades.index.name = "date"
    return StrategyResult(
        name=f"{schedule.candidate.name}_same_close_diagnostic",
        daily=daily,
        trades=trades.reset_index(),
    )


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = pd.to_numeric(daily["net_return"], errors="coerce").dropna()
    if returns.empty:
        raise ValueError("no returns available")
    years = len(returns) / 252.0
    wealth = (1.0 + returns).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = (
        float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
        if years > 0.0 and wealth.iloc[-1] > 0.0
        else -1.0
    )
    drawdown = wealth / wealth.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0))
        if returns.std(ddof=0) > 0.0
        else 0.0
    )
    downside = float(
        np.sqrt(returns.clip(upper=0.0).pow(2).mean()) * np.sqrt(252.0)
    )
    sortino = float(returns.mean() * 252.0 / downside) if downside > 0.0 else 0.0
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0
    turnover = float(daily.loc[returns.index, "turnover_units"].sum())
    position_column = (
        "position_at_open" if "position_at_open" in daily else "position_at_close"
    )
    return {
        "sessions": float(len(returns)),
        "years": years,
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover_units": turnover,
        "round_trips_per_year": turnover / (2.0 * years) if years > 0.0 else 0.0,
        "exposure": float(daily.loc[returns.index, position_column].mean()),
    }


def window_metrics(
    result: StrategyResult,
    *,
    start: str,
    end: str,
) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty window {start} to {end}")
    return metrics(block)


def candidate_development_table(
    results: dict[str, StrategyResult],
    v1_result: StrategyResult,
) -> pd.DataFrame:
    start, end = EVALUATION_WINDOWS["development"]
    v1_metrics = window_metrics(v1_result, start=start, end=end)
    rows: list[dict[str, Any]] = []
    for spec in CANDIDATES:
        item = window_metrics(results[spec.name], start=start, end=end)
        rows.append(
            {
                "candidate": spec.name,
                "core_position": spec.core_position,
                "atr_multiple": spec.atr_multiple,
                "exit_confirmation_days": spec.exit_confirmation_days,
                "complexity_rank": spec.complexity_rank,
                **item,
                "development_cagr_vs_v1_pp": (
                    item["cagr"] - v1_metrics["cagr"]
                )
                * 100.0,
                "development_selection_gate": item["cagr"]
                >= v1_metrics["cagr"] - 0.01,
            }
        )
    table = pd.DataFrame(rows)
    return table.sort_values(
        [
            "development_selection_gate",
            "calmar",
            "cagr",
            "round_trips_per_year",
            "complexity_rank",
        ],
        ascending=[False, False, False, True, True],
    ).reset_index(drop=True)


def select_candidate(development: pd.DataFrame) -> tuple[str, bool]:
    eligible = development.loc[development["development_selection_gate"]]
    if not eligible.empty:
        return str(eligible.iloc[0]["candidate"]), True
    return str(development.iloc[0]["candidate"]), False


def tactical_episode_table(
    dataset: pd.DataFrame,
    result: StrategyResult,
    spec: CandidateSpec,
    *,
    cost_bps: float,
) -> pd.DataFrame:
    daily = result.daily.copy()
    asset_return = dataset["open"].shift(-1) / dataset["open"] - 1.0
    asset_return = asset_return.reindex(daily.index)
    tactical_weight = (
        daily["position_at_open"] - spec.core_position
    ).clip(lower=0.0)
    tactical_turnover = tactical_weight.diff().abs()
    tactical_turnover.iloc[0] = abs(float(tactical_weight.iloc[0]))
    tactical_net = (
        tactical_weight * asset_return
        - tactical_turnover * cost_bps / 10_000.0
    )
    active = tactical_weight.gt(1e-12)
    starts = active & ~active.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(active)

    rows: list[dict[str, Any]] = []
    for raw_id, block in tactical_net.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        episode_return = float((1.0 + block).prod() - 1.0)
        rows.append(
            {
                "episode_id": int(raw_id),
                "entry_open_date": block.index[0],
                "exit_open_date": block.index[-1],
                "eligible_intervals": int(len(block)),
                "tactical_net_return": episode_return,
            }
        )
    table = pd.DataFrame(rows)
    if not table.empty:
        positive = table["tactical_net_return"].clip(lower=0.0)
        total_positive = float(positive.sum())
        table["positive_return_share"] = (
            positive / total_positive if total_positive > 0.0 else 0.0
        )
    return table


def annual_return_table(
    candidate: StrategyResult,
    v1: StrategyResult,
    buy_hold: StrategyResult,
) -> pd.DataFrame:
    frames = {
        "candidate": candidate.daily["net_return"],
        "canonical_v1_0": v1.daily["net_return"],
        "buy_hold": buy_hold.daily["net_return"],
    }
    rows: list[dict[str, Any]] = []
    for name, series in frames.items():
        clean = series.dropna()
        for year, block in clean.groupby(clean.index.year):
            rows.append(
                {
                    "model": name,
                    "year": int(year),
                    "return": float((1.0 + block).prod() - 1.0),
                }
            )
    return pd.DataFrame(rows)


def evaluation_table(
    named_results: dict[str, StrategyResult],
    *,
    cost_bps: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, result in named_results.items():
        for window, (start, end) in EVALUATION_WINDOWS.items():
            rows.append(
                {
                    "model": model,
                    "cost_bps": cost_bps,
                    "window": window,
                    **window_metrics(result, start=start, end=end),
                }
            )
    return pd.DataFrame(rows)


def period_relative_concentration(
    candidate: StrategyResult,
    v1: StrategyResult,
) -> tuple[pd.DataFrame, float]:
    rows: list[dict[str, Any]] = []
    for window in (
        "development",
        "fixed_validation",
        "retrospective_2025_plus",
    ):
        start, end = EVALUATION_WINDOWS[window]
        candidate_return = window_metrics(candidate, start=start, end=end)[
            "total_return"
        ]
        v1_return = window_metrics(v1, start=start, end=end)["total_return"]
        relative = (1.0 + candidate_return) / (1.0 + v1_return) - 1.0
        rows.append(
            {
                "window": window,
                "candidate_return": candidate_return,
                "v1_return": v1_return,
                "relative_return": relative,
                "positive_relative_return": max(relative, 0.0),
            }
        )
    table = pd.DataFrame(rows)
    total_positive = float(table["positive_relative_return"].sum())
    table["positive_relative_share"] = (
        table["positive_relative_return"] / total_positive
        if total_positive > 0.0
        else 0.0
    )
    largest = (
        float(table["positive_relative_share"].max())
        if total_positive > 0.0
        else 1.0
    )
    return table, largest


def governed_decision(
    selected_name: str,
    selection_gate_pass: bool,
    results_20: dict[str, StrategyResult],
    results_40: dict[str, StrategyResult],
    v1_20: StrategyResult,
    v1_40: StrategyResult,
    buy_hold_20: StrategyResult,
    episodes: pd.DataFrame,
    period_concentration: float,
) -> dict[str, Any]:
    selected_20 = results_20[selected_name]
    selected_40 = results_40[selected_name]
    full_start, full_end = EVALUATION_WINDOWS["full_history"]
    val_start, val_end = EVALUATION_WINDOWS["fixed_validation"]
    retro_start, retro_end = EVALUATION_WINDOWS["retrospective_2025_plus"]

    candidate_full = window_metrics(selected_20, start=full_start, end=full_end)
    v1_full = window_metrics(v1_20, start=full_start, end=full_end)
    buy_full = window_metrics(buy_hold_20, start=full_start, end=full_end)
    candidate_val = window_metrics(selected_20, start=val_start, end=val_end)
    v1_val = window_metrics(v1_20, start=val_start, end=val_end)
    buy_val = window_metrics(buy_hold_20, start=val_start, end=val_end)
    candidate_retro = window_metrics(
        selected_20, start=retro_start, end=retro_end
    )
    v1_retro = window_metrics(v1_20, start=retro_start, end=retro_end)
    candidate_full_40 = window_metrics(
        selected_40, start=full_start, end=full_end
    )
    v1_full_40 = window_metrics(v1_40, start=full_start, end=full_end)

    largest_episode_share = (
        float(episodes["positive_return_share"].max())
        if not episodes.empty and "positive_return_share" in episodes
        else 1.0
    )
    gates = {
        "development_selection_gate": bool(selection_gate_pass),
        "full_cagr_above_buy_hold": candidate_full["cagr"] > buy_full["cagr"],
        "full_cagr_above_v1": candidate_full["cagr"] > v1_full["cagr"],
        "full_calmar_not_below_buy_hold": candidate_full["calmar"]
        >= buy_full["calmar"],
        "full_calmar_not_below_v1": candidate_full["calmar"]
        >= v1_full["calmar"],
        "validation_total_not_below_buy_hold": candidate_val["total_return"]
        >= buy_val["total_return"],
        "validation_total_not_below_v1": candidate_val["total_return"]
        >= v1_val["total_return"],
        "validation_drawdown_not_worse_than_buy_hold": candidate_val[
            "max_drawdown"
        ]
        >= buy_val["max_drawdown"],
        "retrospective_total_within_1pp_of_v1": candidate_retro["total_return"]
        >= v1_retro["total_return"] - 0.01,
        "stress_40bps_full_cagr_above_v1": candidate_full_40["cagr"]
        > v1_full_40["cagr"],
        "round_trips_per_year_le_3": candidate_full["round_trips_per_year"]
        <= 3.0,
        "largest_positive_episode_share_le_50pct": largest_episode_share <= 0.50,
        "largest_positive_period_share_le_60pct": period_concentration <= 0.60,
    }
    outperforming = all(gates.values())

    claimant = results_20["claimant_flat_atr32"]
    claimant_full = window_metrics(claimant, start=full_start, end=full_end)
    risk_improved = (
        candidate_full["calmar"] > claimant_full["calmar"]
        or candidate_full["max_drawdown"] > claimant_full["max_drawdown"] + 0.01
    )
    not_dominated_by_claimant = (
        candidate_full["cagr"] >= claimant_full["cagr"] - 0.005
        or candidate_full["calmar"] >= claimant_full["calmar"]
    )
    if outperforming:
        decision = "supported_outperforming"
    elif risk_improved and not_dominated_by_claimant:
        decision = "improved_but_not_outperforming"
    else:
        decision = "not_supported"

    return {
        "decision": decision,
        "selected_candidate": selected_name,
        "selection_gate_pass": bool(selection_gate_pass),
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
        "gates": gates,
        "largest_positive_episode_share": largest_episode_share,
        "largest_positive_period_share": period_concentration,
        "selected_full_history_20bps": candidate_full,
        "canonical_v1_full_history_20bps": v1_full,
        "buy_hold_full_history_20bps": buy_full,
        "selected_fixed_validation_20bps": candidate_val,
        "canonical_v1_fixed_validation_20bps": v1_val,
        "buy_hold_fixed_validation_20bps": buy_val,
        "selected_retrospective_2025_plus_20bps": candidate_retro,
        "canonical_v1_retrospective_2025_plus_20bps": v1_retro,
        "selected_full_history_40bps": candidate_full_40,
        "canonical_v1_full_history_40bps": v1_full_40,
    }


def build_all(
    adjusted: pd.DataFrame,
    sessions: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, DecisionSchedule]]:
    dataset = add_claim_features(build_research_dataset(adjusted, sessions))
    schedules = {
        spec.name: build_candidate_schedule(dataset, spec) for spec in CANDIDATES
    }
    return dataset, schedules
