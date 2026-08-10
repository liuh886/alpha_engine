"""Profit-retaining core/tactical research baseline for BYD A shares.

This module is the governed follow-up to the rejected binary long/cash screen.
It evaluates a frozen family of 50%/75% core positions with a tactical sleeve.
Signals are decided at the session close and executed at the next session open.
The result is research-only and requires prospective confirmation.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.byd_single_asset_v1 import (
    BacktestResult,
    normalise_ohlcv,
    run_backtest,
    run_buy_and_hold,
)

CANDIDATE_NAMES = (
    "core75_regime_mom_120",
    "core50_regime_mom_120",
    "core75_regime_60_200",
    "core50_regime_60_200",
    "core75_dd20_recovery10",
    "core50_dd20_recovery10",
    "core75_momentum_20_120",
)


def _stateful(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    if not entry.index.equals(exit_.index):
        raise ValueError("entry and exit indices must match")
    active = False
    states: list[float] = []
    for enter_now, exit_now in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        states.append(1.0 if active else 0.0)
    return pd.Series(states, index=entry.index, dtype=float)


def build_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Build only the close-observable features frozen in Issue #500."""

    daily = normalise_ohlcv(ohlcv).copy()
    close = daily["close"]
    daily["sma_20"] = close.rolling(20, min_periods=20).mean()
    daily["sma_60"] = close.rolling(60, min_periods=60).mean()
    daily["sma_120"] = close.rolling(120, min_periods=120).mean()
    daily["sma_200"] = close.rolling(200, min_periods=200).mean()
    daily["momentum_20"] = close.pct_change(20)
    daily["momentum_60"] = close.pct_change(60)
    daily["rolling_high_252"] = close.rolling(252, min_periods=120).max()
    daily["drawdown_252"] = close.div(daily["rolling_high_252"]).sub(1.0)
    return daily


def build_candidate_positions(features: pd.DataFrame) -> dict[str, pd.Series]:
    """Return the seven frozen close-time target-position series."""

    close = features["close"]
    regime_mom_120 = _stateful(
        entry=close.gt(features["sma_120"]) & features["momentum_20"].gt(0.0),
        exit_=close.lt(features["sma_120"]) & features["momentum_60"].lt(0.0),
    )
    regime_60_200 = _stateful(
        entry=close.gt(features["sma_200"]) & features["sma_60"].gt(features["sma_200"]),
        exit_=close.lt(features["sma_120"]) & features["sma_60"].lt(features["sma_200"]),
    )
    risk_off_drawdown = _stateful(
        entry=features["drawdown_252"].le(-0.20) & close.lt(features["sma_120"]),
        exit_=features["drawdown_252"].ge(-0.10) & close.gt(features["sma_60"]),
    )
    drawdown_risk_on = 1.0 - risk_off_drawdown
    symmetric_momentum = _stateful(
        entry=close.gt(features["sma_120"]) & features["momentum_20"].gt(0.0),
        exit_=close.lt(features["sma_120"]) | features["momentum_20"].lt(0.0),
    )

    positions = {
        "core75_regime_mom_120": 0.75 + 0.25 * regime_mom_120,
        "core50_regime_mom_120": 0.50 + 0.50 * regime_mom_120,
        "core75_regime_60_200": 0.75 + 0.25 * regime_60_200,
        "core50_regime_60_200": 0.50 + 0.50 * regime_60_200,
        "core75_dd20_recovery10": 0.75 + 0.25 * drawdown_risk_on,
        "core50_dd20_recovery10": 0.50 + 0.50 * drawdown_risk_on,
        "core75_momentum_20_120": 0.75 + 0.25 * symmetric_momentum,
    }
    if tuple(positions) != CANDIDATE_NAMES:
        raise AssertionError("core/tactical candidate set drifted from the contract")
    for name, position in positions.items():
        position.name = "decision_position"
        observed = set(position.dropna().unique())
        allowed = {0.50, 0.75, 1.0}
        if not observed.issubset(allowed):
            raise AssertionError(f"{name} produced an undeclared position: {observed}")
        if float(position.min()) < 0.50 or float(position.max()) > 1.0:
            raise AssertionError(f"{name} violated the 50%-100% position boundary")
    return positions


def _metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = pd.to_numeric(daily["net_return"], errors="coerce").dropna()
    if returns.empty:
        raise ValueError("no returns available for metrics")
    years = len(returns) / 252.0
    wealth = (1.0 + returns).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = (
        float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
        if years > 0.0 and wealth.iloc[-1] > 0.0
        else -1.0
    )
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0))
        if returns.std(ddof=0) > 0.0
        else 0.0
    )
    downside_deviation = float(np.sqrt(returns.clip(upper=0.0).pow(2).mean()) * np.sqrt(252.0))
    sortino = (
        float(returns.mean() * 252.0 / downside_deviation) if downside_deviation > 0.0 else 0.0
    )
    drawdown = wealth.div(wealth.cummax()).sub(1.0)
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0
    turnover_units = float(daily["turnover_units"].sum())
    return {
        "sessions": float(len(returns)),
        "years": float(years),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover_units": turnover_units,
        "round_trips_per_year": (float(turnover_units / (2.0 * years)) if years > 0.0 else 0.0),
        "exposure": float(daily["position_at_open"].mean()),
    }


def _slice_daily(result: BacktestResult, start: str, end: str) -> pd.DataFrame:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
    if block.empty:
        raise ValueError(f"empty evaluation window {start} to {end}")
    return block


def _yearly_comparison(
    candidate_daily: pd.DataFrame, benchmark_daily: pd.DataFrame
) -> pd.DataFrame:
    candidate = candidate_daily.groupby(candidate_daily.index.year)["net_return"].apply(
        lambda values: float((1.0 + values).prod() - 1.0)
    )
    benchmark = benchmark_daily.groupby(benchmark_daily.index.year)["net_return"].apply(
        lambda values: float((1.0 + values).prod() - 1.0)
    )
    comparison = pd.DataFrame(
        {"candidate_return": candidate, "buy_hold_return": benchmark}
    ).dropna()
    comparison["relative_return"] = (
        (1.0 + comparison["candidate_return"]).div(1.0 + comparison["buy_hold_return"]).sub(1.0)
    )
    comparison.index.name = "year"
    return comparison


def _defense_episodes(candidate_daily: pd.DataFrame, benchmark_daily: pd.DataFrame) -> pd.DataFrame:
    aligned_benchmark = benchmark_daily.reindex(candidate_daily.index)
    if aligned_benchmark["net_return"].isna().any():
        raise ValueError("benchmark is missing candidate dates")
    risk_off = candidate_daily["position_at_open"].lt(1.0 - 1e-12)
    starts = risk_off & ~risk_off.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(risk_off)
    records: list[dict[str, Any]] = []
    for raw_id, block in candidate_daily.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        benchmark_block = aligned_benchmark.loc[block.index]
        candidate_return = float((1.0 + block["net_return"]).prod() - 1.0)
        buy_hold_return = float((1.0 + benchmark_block["net_return"]).prod() - 1.0)
        relative_return = float((1.0 + candidate_return) / (1.0 + buy_hold_return) - 1.0)
        records.append(
            {
                "episode_id": int(raw_id),
                "start": block.index[0],
                "end": block.index[-1],
                "sessions": int(len(block)),
                "minimum_position": float(block["position_at_open"].min()),
                "candidate_return": candidate_return,
                "buy_hold_return": buy_hold_return,
                "relative_return": relative_return,
            }
        )
    return pd.DataFrame.from_records(records)


def _largest_positive_episode_share(episodes: pd.DataFrame) -> float:
    if episodes.empty:
        return 1.0
    positive = episodes["relative_return"].clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else 1.0


def evaluate_research(ohlcv: pd.DataFrame, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Select a profit-retaining core/tactical rule and run the holdout check."""

    features = build_features(ohlcv)
    positions = build_candidate_positions(features)
    primary_cost = float(contract["costs"]["primary_bps_per_turnover_unit"])
    stress_cost = float(max(contract["costs"]["stress_bps_per_turnover_unit"]))
    windows = contract["windows"]
    selection_start = str(windows["development_start"])
    selection_end = str(windows["validation_end"])
    validation_start = str(windows["validation_start"])
    validation_end = str(windows["validation_end"])
    holdout_start = str(windows["retrospective_holdout_start"])
    holdout_end = str(windows["retrospective_holdout_end"])

    benchmark_full = run_buy_and_hold(features, primary_cost)
    benchmark_selection_daily = _slice_daily(benchmark_full, selection_start, selection_end)
    benchmark_validation_daily = _slice_daily(benchmark_full, validation_start, validation_end)
    benchmark_holdout_daily = _slice_daily(benchmark_full, holdout_start, holdout_end)
    benchmark_selection = _metrics(benchmark_selection_daily)
    benchmark_validation = _metrics(benchmark_validation_daily)
    benchmark_holdout = _metrics(benchmark_holdout_daily)

    full_results: dict[str, BacktestResult] = {}
    candidate_rows: list[dict[str, Any]] = []
    for name in CANDIDATE_NAMES:
        full = run_backtest(features, positions[name], primary_cost, name)
        full_results[name] = full
        selection_daily = _slice_daily(full, selection_start, selection_end)
        validation_daily = _slice_daily(full, validation_start, validation_end)
        selection = _metrics(selection_daily)
        validation = _metrics(validation_daily)
        stress_full = run_backtest(features, positions[name], stress_cost, name)
        stress_selection = _metrics(_slice_daily(stress_full, selection_start, selection_end))
        episodes = _defense_episodes(selection_daily, benchmark_selection_daily)
        largest_episode_share = _largest_positive_episode_share(episodes)
        cagr_retention = (
            selection["cagr"] / benchmark_selection["cagr"]
            if benchmark_selection["cagr"] > 0.0
            else 0.0
        )
        gates = {
            "selection_cagr_retention_95pct": cagr_retention >= 0.95,
            "selection_calmar_not_below_buy_hold": selection["calmar"]
            >= benchmark_selection["calmar"],
            "selection_drawdown_improvement_2pp": selection["max_drawdown"]
            - benchmark_selection["max_drawdown"]
            >= 0.02,
            "validation_positive_total_return": validation["total_return"] > 0.0,
            "validation_cagr_within_1pp": validation["cagr"] >= benchmark_validation["cagr"] - 0.01,
            "validation_calmar_not_below_buy_hold": validation["calmar"]
            >= benchmark_validation["calmar"],
            "validation_drawdown_improvement_4pp": validation["max_drawdown"]
            - benchmark_validation["max_drawdown"]
            >= 0.04,
            "turnover_cap": selection["round_trips_per_year"] <= 2.0,
            "stress_40_positive": stress_selection["total_return"] > 0.0,
            "defense_episode_concentration_cap": largest_episode_share <= 0.50,
        }
        candidate_rows.append(
            {
                "candidate": name,
                "selection_metrics": selection,
                "validation_metrics": validation,
                "selection_cagr_retention": cagr_retention,
                "selection_stress_40_metrics": stress_selection,
                "largest_positive_defense_episode_share": largest_episode_share,
                "defense_episodes": episodes.to_dict(orient="records"),
                "yearly_comparison": _yearly_comparison(selection_daily, benchmark_selection_daily)
                .reset_index()
                .to_dict(orient="records"),
                "selection_gates": gates,
                "selection_pass": all(gates.values()),
            }
        )

    passing = [row for row in candidate_rows if row["selection_pass"]]
    passing.sort(
        key=lambda row: (
            row["selection_metrics"]["cagr"],
            row["validation_metrics"]["calmar"],
            row["validation_metrics"]["max_drawdown"],
            -row["selection_metrics"]["round_trips_per_year"],
        ),
        reverse=True,
    )
    selected_name = passing[0]["candidate"] if passing else None
    decision = "byd_v1_0_core_tactical_not_supported"
    holdout: dict[str, Any] | None = None

    if selected_name is not None:
        selected_full = full_results[selected_name]
        selected_holdout_daily = _slice_daily(selected_full, holdout_start, holdout_end)
        selected_holdout = _metrics(selected_holdout_daily)
        stress_holdout_full = run_backtest(
            features, positions[selected_name], stress_cost, selected_name
        )
        stress_holdout = _metrics(_slice_daily(stress_holdout_full, holdout_start, holdout_end))
        holdout_gates = {
            "positive_total_return": selected_holdout["total_return"] > 0.0,
            "cagr_not_below_buy_hold": selected_holdout["cagr"] >= benchmark_holdout["cagr"],
            "calmar_not_below_buy_hold": selected_holdout["calmar"] >= benchmark_holdout["calmar"],
            "drawdown_improvement_4pp": selected_holdout["max_drawdown"]
            - benchmark_holdout["max_drawdown"]
            >= 0.04,
            "stress_40_positive": stress_holdout["total_return"] > 0.0,
            "not_unanimously_worse": not (
                selected_holdout["cagr"] < benchmark_holdout["cagr"]
                and selected_holdout["calmar"] < benchmark_holdout["calmar"]
                and selected_holdout["max_drawdown"] < benchmark_holdout["max_drawdown"]
            ),
        }
        holdout = {
            "classification": "retrospective_holdout",
            "prospective_confirmation_required": True,
            "candidate_metrics": selected_holdout,
            "buy_hold_metrics": benchmark_holdout,
            "stress_40_metrics": stress_holdout,
            "gates": holdout_gates,
            "pass": all(holdout_gates.values()),
            "defense_episodes": _defense_episodes(
                selected_holdout_daily, benchmark_holdout_daily
            ).to_dict(orient="records"),
        }
        if holdout["pass"]:
            decision = "byd_v1_0_core_tactical_supported"

    latest_signals = {name: float(position.iloc[-1]) for name, position in positions.items()}
    latest_open_positions = {
        name: float(full_results[name].daily["position_at_open"].iloc[-1])
        for name in CANDIDATE_NAMES
    }
    selected_latest_signal = latest_signals.get(selected_name) if selected_name else None
    selected_current_position = latest_open_positions.get(selected_name) if selected_name else None

    return {
        "experiment_id": str(contract["experiment_id"]),
        "parent_issue": int(contract["parent_issue"]),
        "research_only": True,
        "trade_ready": False,
        "prospective_confirmation_required": True,
        "decision": decision,
        "selected_candidate": selected_name,
        "latest_data_date": features.index[-1].strftime("%Y-%m-%d"),
        "selected_latest_close_target_for_next_open": selected_latest_signal,
        "selected_current_open_position": selected_current_position,
        "candidate_rows": candidate_rows,
        "buy_hold_selection_metrics": benchmark_selection,
        "buy_hold_validation_metrics": benchmark_validation,
        "buy_hold_holdout_metrics": benchmark_holdout,
        "retrospective_holdout": holdout,
        "latest_candidate_targets": latest_signals,
        "latest_candidate_open_positions": latest_open_positions,
    }
