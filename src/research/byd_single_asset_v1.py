"""Governed single-asset medium-frequency research for BYD A shares.

The module evaluates a frozen set of interpretable long/cash strategies. Signals
are decided at session close and become executable at the next session open.
It is research-only and intentionally excludes shorting, leverage, intraday
execution and post-result parameter search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

CANDIDATE_NAMES = (
    "trend_20_60",
    "breakout_55_20",
    "momentum_20_120",
    "rsi_trend_reversion",
    "bollinger_trend_reversion",
)

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
_COLUMN_ALIASES = {
    "日期": "date",
    "交易日期": "date",
    "date": "date",
    "datetime": "date",
    "开盘": "open",
    "open": "open",
    "最高": "high",
    "high": "high",
    "最低": "low",
    "low": "low",
    "收盘": "close",
    "close": "close",
    "成交量": "volume",
    "volume": "volume",
}


@dataclass(frozen=True)
class BacktestResult:
    """One strategy result with auditable daily, yearly and trade evidence."""

    name: str
    daily: pd.DataFrame
    metrics: dict[str, float]
    yearly: pd.DataFrame
    trades: pd.DataFrame


def normalise_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return validated, date-indexed OHLCV without filling missing observations."""

    if frame.empty:
        raise ValueError("OHLCV input is empty")
    renamed = frame.rename(
        columns={
            column: _COLUMN_ALIASES.get(str(column), str(column).lower())
            for column in frame.columns
        }
    )
    if "date" in renamed.columns:
        dates = pd.to_datetime(renamed.pop("date"), errors="coerce")
    else:
        dates = pd.to_datetime(renamed.index, errors="coerce")
    if dates.isna().any():
        raise ValueError("OHLCV contains an invalid date")

    missing = sorted(set(_REQUIRED_COLUMNS) - set(renamed.columns))
    if missing:
        raise ValueError(f"OHLCV missing required columns: {missing}")

    daily = renamed.loc[:, list(_REQUIRED_COLUMNS)].copy()
    daily.index = pd.DatetimeIndex(dates).tz_localize(None)
    daily.index.name = "date"
    daily = daily.sort_index()
    if daily.index.has_duplicates:
        duplicates = daily.index[daily.index.duplicated()].strftime("%Y-%m-%d").tolist()
        raise ValueError(f"OHLCV contains duplicate dates: {duplicates[:5]}")
    if not daily.index.is_monotonic_increasing:
        raise ValueError("OHLCV index must be monotonic increasing")

    for column in _REQUIRED_COLUMNS:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    if daily[list(_REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("OHLCV contains non-numeric or missing required values")
    if (daily[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (daily["volume"] < 0.0).any():
        raise ValueError("volume cannot be negative")
    if (daily["high"] < daily[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("high is below another OHLC field")
    if (daily["low"] > daily[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("low is above another OHLC field")
    if len(daily) < 260:
        raise ValueError("at least 260 daily observations are required")
    return daily


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    relative_strength = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + relative_strength)
    rsi = rsi.where(avg_loss.ne(0.0), 100.0)
    rsi = rsi.where(avg_gain.ne(0.0), 0.0)
    both_zero = avg_gain.eq(0.0) & avg_loss.eq(0.0)
    return rsi.where(~both_zero, 50.0).rename("rsi_14")


def build_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Build the frozen close-observable feature set."""

    daily = normalise_ohlcv(ohlcv).copy()
    close = daily["close"]
    daily["sma_20"] = close.rolling(20, min_periods=20).mean()
    daily["sma_60"] = close.rolling(60, min_periods=60).mean()
    daily["sma_120"] = close.rolling(120, min_periods=120).mean()
    daily["momentum_20"] = close.pct_change(20)
    daily["prior_high_55"] = (
        daily["high"].rolling(55, min_periods=55).max().shift(1)
    )
    daily["prior_low_20"] = daily["low"].rolling(20, min_periods=20).min().shift(1)
    daily["rsi_14"] = _wilder_rsi(close, 14)
    rolling_std = close.rolling(20, min_periods=20).std(ddof=0)
    daily["bollinger_lower_20_2"] = daily["sma_20"] - 2.0 * rolling_std
    return daily


def _stateful_position(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    if not entry.index.equals(exit_.index):
        raise ValueError("entry and exit indices must match")
    active = False
    states: list[float] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        states.append(1.0 if active else 0.0)
    return pd.Series(
        states, index=entry.index, dtype=float, name="decision_position"
    )


def build_candidate_positions(features: pd.DataFrame) -> dict[str, pd.Series]:
    """Build the five pre-registered close-time long/cash decisions."""

    close = features["close"]
    trend_20_60 = _stateful_position(
        entry=close.gt(features["sma_60"])
        & features["sma_20"].gt(features["sma_60"]),
        exit_=close.lt(features["sma_20"])
        | features["sma_20"].lt(features["sma_60"]),
    )
    breakout_55_20 = _stateful_position(
        entry=close.gt(features["prior_high_55"]),
        exit_=close.lt(features["prior_low_20"]),
    )
    momentum_20_120 = _stateful_position(
        entry=close.gt(features["sma_120"])
        & features["momentum_20"].gt(0.0),
        exit_=close.lt(features["sma_120"])
        | features["momentum_20"].lt(0.0),
    )
    rsi_trend_reversion = _stateful_position(
        entry=close.gt(features["sma_120"])
        & features["rsi_14"].lt(35.0),
        exit_=close.lt(features["sma_120"])
        | features["rsi_14"].gt(55.0),
    )
    bollinger_trend_reversion = _stateful_position(
        entry=close.gt(features["sma_120"])
        & close.lt(features["bollinger_lower_20_2"]),
        exit_=close.lt(features["sma_120"]) | close.ge(features["sma_20"]),
    )
    positions = {
        "trend_20_60": trend_20_60,
        "breakout_55_20": breakout_55_20,
        "momentum_20_120": momentum_20_120,
        "rsi_trend_reversion": rsi_trend_reversion,
        "bollinger_trend_reversion": bollinger_trend_reversion,
    }
    if tuple(positions) != CANDIDATE_NAMES:
        raise AssertionError("candidate set drifted from the frozen contract")
    for name, position in positions.items():
        if not set(position.dropna().unique()).issubset({0.0, 1.0}):
            raise AssertionError(f"{name} produced a non-binary position")
    return positions


def _return_metrics(
    returns: pd.Series, position: pd.Series, turnover: pd.Series
) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        raise ValueError("no returns available for metrics")
    aligned_position = position.reindex(clean.index).fillna(0.0)
    aligned_turnover = turnover.reindex(clean.index).fillna(0.0)
    years = len(clean) / 252.0
    wealth = (1.0 + clean).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = (
        float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
        if years > 0.0 and wealth.iloc[-1] > 0.0
        else -1.0
    )
    volatility = float(clean.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(clean.mean() / clean.std(ddof=0) * np.sqrt(252.0))
        if clean.std(ddof=0) > 0.0
        else 0.0
    )
    downside = clean.clip(upper=0.0)
    downside_deviation = float(
        np.sqrt((downside.pow(2)).mean()) * np.sqrt(252.0)
    )
    sortino = (
        float(clean.mean() * 252.0 / downside_deviation)
        if downside_deviation > 0.0
        else 0.0
    )
    drawdown = wealth.div(wealth.cummax()).sub(1.0)
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0
    turnover_units = float(aligned_turnover.sum())
    round_trips_per_year = (
        float(turnover_units / (2.0 * years)) if years > 0.0 else 0.0
    )
    return {
        "sessions": float(len(clean)),
        "years": float(years),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover_units": turnover_units,
        "round_trips_per_year": round_trips_per_year,
        "exposure": float(aligned_position.mean()),
    }


def _build_trades(daily: pd.DataFrame) -> pd.DataFrame:
    position = daily["position_at_open"]
    changes = position.diff().fillna(position)
    active_trade: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []
    trade_id = 0
    labels = pd.Series(np.nan, index=daily.index, dtype=float)
    for date, change in changes.items():
        if change > 0.5:
            trade_id += 1
            active_trade = {
                "trade_id": trade_id,
                "entry_date": date,
                "entry_open": float(daily.loc[date, "open"]),
            }
        if active_trade is not None and position.loc[date] > 0.5:
            labels.loc[date] = float(active_trade["trade_id"])
        if change < -0.5 and active_trade is not None:
            active_trade["exit_date"] = date
            active_trade["exit_open"] = float(daily.loc[date, "open"])
            active_trade["gross_return"] = (
                active_trade["exit_open"] / active_trade["entry_open"] - 1.0
            )
            records.append(active_trade)
            active_trade = None
    if active_trade is not None:
        active_trade["exit_date"] = pd.NaT
        active_trade["exit_open"] = np.nan
        trade_returns = daily.loc[
            labels.eq(float(active_trade["trade_id"])), "net_return"
        ]
        active_trade["gross_return"] = float(
            (1.0 + trade_returns).prod() - 1.0
        )
        records.append(active_trade)
    daily["trade_id"] = labels
    columns = [
        "trade_id",
        "entry_date",
        "exit_date",
        "entry_open",
        "exit_open",
        "gross_return",
    ]
    return pd.DataFrame.from_records(records, columns=columns)


def run_backtest(
    features: pd.DataFrame,
    decision_position: pd.Series,
    cost_bps: float,
    name: str,
) -> BacktestResult:
    """Execute close-decided positions at the next open with explicit turnover costs."""

    if cost_bps < 0.0:
        raise ValueError("cost_bps cannot be negative")
    daily = features.loc[:, ["open", "high", "low", "close", "volume"]].copy()
    decision = decision_position.reindex(daily.index)
    if decision.isna().any():
        raise ValueError("decision position has missing dates")
    daily["decision_position"] = decision.astype(float)
    daily["position_at_open"] = daily["decision_position"].shift(1).fillna(0.0)
    daily["asset_open_to_open_return"] = (
        daily["open"].shift(-1).div(daily["open"]).sub(1.0)
    )
    daily = daily.iloc[:-1].copy()
    daily["turnover_units"] = (
        daily["position_at_open"]
        .diff()
        .abs()
        .fillna(daily["position_at_open"].abs())
    )
    daily["transaction_cost"] = (
        daily["turnover_units"] * float(cost_bps) / 10_000.0
    )
    daily["gross_return"] = (
        daily["position_at_open"] * daily["asset_open_to_open_return"]
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["wealth"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["wealth"].div(daily["wealth"].cummax()).sub(1.0)
    trades = _build_trades(daily)
    metrics = _return_metrics(
        daily["net_return"], daily["position_at_open"], daily["turnover_units"]
    )
    metrics["trade_count"] = float(len(trades))

    yearly_records: list[dict[str, float]] = []
    for year, block in daily.groupby(daily.index.year):
        yearly_records.append(
            {
                "year": float(year),
                "strategy_return": float((1.0 + block["net_return"]).prod() - 1.0),
            }
        )
    yearly = (
        pd.DataFrame(yearly_records).set_index("year")
        if yearly_records
        else pd.DataFrame(columns=["strategy_return"])
    )
    return BacktestResult(
        name=name, daily=daily, metrics=metrics, yearly=yearly, trades=trades
    )


def run_buy_and_hold(features: pd.DataFrame, cost_bps: float) -> BacktestResult:
    decision = pd.Series(
        1.0, index=features.index, dtype=float, name="decision_position"
    )
    return run_backtest(features, decision, cost_bps, "buy_hold_byd")


def _slice_result(
    result: BacktestResult, start: str, end: str
) -> BacktestResult:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
    if block.empty:
        raise ValueError(f"empty evaluation window {start} to {end}")
    metrics = _return_metrics(
        block["net_return"], block["position_at_open"], block["turnover_units"]
    )
    trade_ids = block["trade_id"].dropna().unique().tolist()
    trades = (
        result.trades[result.trades["trade_id"].isin(trade_ids)].copy()
        if not result.trades.empty
        else result.trades.copy()
    )
    metrics["trade_count"] = float(len(trades))
    yearly_records = []
    for year, year_block in block.groupby(block.index.year):
        yearly_records.append(
            {
                "year": float(year),
                "strategy_return": float(
                    (1.0 + year_block["net_return"]).prod() - 1.0
                ),
            }
        )
    yearly = pd.DataFrame(yearly_records).set_index("year")
    return BacktestResult(result.name, block, metrics, yearly, trades)


def _ex_best_trade_total_return(result: BacktestResult) -> float:
    daily = result.daily.copy()
    if daily["trade_id"].dropna().empty:
        return float((1.0 + daily["net_return"]).prod() - 1.0)
    trade_returns = (
        daily.dropna(subset=["trade_id"])
        .groupby("trade_id")["net_return"]
        .apply(lambda values: float((1.0 + values).prod() - 1.0))
    )
    best_trade_id = float(trade_returns.idxmax())
    reduced = daily.loc[~daily["trade_id"].eq(best_trade_id), "net_return"]
    return float((1.0 + reduced).prod() - 1.0)


def _year_comparison(
    candidate: BacktestResult, benchmark: BacktestResult
) -> pd.DataFrame:
    comparison = candidate.yearly.rename(
        columns={"strategy_return": "candidate_return"}
    ).join(
        benchmark.yearly.rename(columns={"strategy_return": "buy_hold_return"}),
        how="inner",
    )
    comparison["relative_return"] = (
        (1.0 + comparison["candidate_return"])
        .div(1.0 + comparison["buy_hold_return"])
        .sub(1.0)
    )
    return comparison


def _largest_positive_year_share(year_comparison: pd.DataFrame) -> float:
    positive = year_comparison["relative_return"].clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else 1.0


def evaluate_research(
    ohlcv: pd.DataFrame, contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate, select and quarantine-check the frozen BYD V1.0 candidates."""

    features = build_features(ohlcv)
    candidates = build_candidate_positions(features)
    primary_cost = float(contract["costs"]["primary_bps_per_turnover_unit"])
    stress_costs = [
        float(value)
        for value in contract["costs"]["stress_bps_per_turnover_unit"]
    ]
    windows = contract["windows"]
    selection_start = str(windows["development_start"])
    selection_end = str(windows["validation_end"])
    validation_start = str(windows["validation_start"])
    validation_end = str(windows["validation_end"])
    quarantine_start = str(windows["quarantine_start"])
    quarantine_end = str(windows["quarantine_end"])

    benchmark_full = run_buy_and_hold(features, primary_cost)
    benchmark_selection = _slice_result(
        benchmark_full, selection_start, selection_end
    )
    benchmark_validation = _slice_result(
        benchmark_full, validation_start, validation_end
    )
    benchmark_quarantine = _slice_result(
        benchmark_full, quarantine_start, quarantine_end
    )

    full_results: dict[str, BacktestResult] = {}
    rows: list[dict[str, Any]] = []
    for name in CANDIDATE_NAMES:
        full = run_backtest(features, candidates[name], primary_cost, name)
        full_results[name] = full
        selection = _slice_result(full, selection_start, selection_end)
        validation = _slice_result(full, validation_start, validation_end)
        year_comparison = _year_comparison(selection, benchmark_selection)
        positive_year_fraction = float(
            year_comparison["relative_return"].gt(0.0).mean()
        )
        largest_positive_year_share = _largest_positive_year_share(
            year_comparison
        )
        stress_40 = run_backtest(
            features, candidates[name], max(stress_costs), name
        )
        stress_40_selection = _slice_result(
            stress_40, selection_start, selection_end
        )
        ex_best_trade = _ex_best_trade_total_return(selection)
        gates = {
            "calmar_above_buy_hold": selection.metrics["calmar"]
            > benchmark_selection.metrics["calmar"],
            "drawdown_or_sortino_improved": (
                selection.metrics["max_drawdown"]
                - benchmark_selection.metrics["max_drawdown"]
                >= 0.08
                or selection.metrics["sortino"]
                - benchmark_selection.metrics["sortino"]
                >= 0.20
            ),
            "cagr_retention": selection.metrics["cagr"]
            >= benchmark_selection.metrics["cagr"] - 0.05,
            "positive_year_fraction": positive_year_fraction >= 0.50,
            "turnover_cap": selection.metrics["round_trips_per_year"] <= 12.0,
            "year_concentration_cap": largest_positive_year_share <= 0.50,
            "stress_40_positive": stress_40_selection.metrics["total_return"]
            > 0.0,
            "not_best_trade_dependent": ex_best_trade > 0.0,
        }
        rows.append(
            {
                "candidate": name,
                "selection_metrics": selection.metrics,
                "validation_metrics": validation.metrics,
                "positive_year_fraction": positive_year_fraction,
                "largest_positive_year_share": largest_positive_year_share,
                "selection_total_return_ex_best_trade": ex_best_trade,
                "selection_stress_40_total_return": stress_40_selection.metrics[
                    "total_return"
                ],
                "selection_gates": gates,
                "selection_pass": all(gates.values()),
            }
        )

    passing = [row for row in rows if row["selection_pass"]]
    passing.sort(
        key=lambda row: (
            row["validation_metrics"]["calmar"],
            row["validation_metrics"]["max_drawdown"],
            row["validation_metrics"]["cagr"],
            -row["validation_metrics"]["round_trips_per_year"],
        ),
        reverse=True,
    )

    selected_name = passing[0]["candidate"] if passing else None
    quarantine: dict[str, Any] | None = None
    decision = "byd_v1_0_not_supported"
    if selected_name is not None:
        selected_full = full_results[selected_name]
        selected_quarantine = _slice_result(
            selected_full, quarantine_start, quarantine_end
        )
        stress_40_full = run_backtest(
            features, candidates[selected_name], max(stress_costs), selected_name
        )
        stress_40_quarantine = _slice_result(
            stress_40_full, quarantine_start, quarantine_end
        )
        ex_best_trade = _ex_best_trade_total_return(selected_quarantine)
        q_gates = {
            "positive_total_return": selected_quarantine.metrics["total_return"]
            > 0.0,
            "calmar_not_below_buy_hold": selected_quarantine.metrics["calmar"]
            >= benchmark_quarantine.metrics["calmar"],
            "drawdown_not_materially_worse": selected_quarantine.metrics[
                "max_drawdown"
            ]
            >= benchmark_quarantine.metrics["max_drawdown"] - 0.03,
            "not_both_cagr_and_sortino_lower": not (
                selected_quarantine.metrics["cagr"]
                < benchmark_quarantine.metrics["cagr"]
                and selected_quarantine.metrics["sortino"]
                < benchmark_quarantine.metrics["sortino"]
            ),
            "positive_ex_best_trade": ex_best_trade > 0.0,
            "stress_40_not_below_minus_5pct": stress_40_quarantine.metrics[
                "total_return"
            ]
            >= -0.05,
        }
        quarantine = {
            "candidate_metrics": selected_quarantine.metrics,
            "buy_hold_metrics": benchmark_quarantine.metrics,
            "total_return_ex_best_trade": ex_best_trade,
            "stress_40_total_return": stress_40_quarantine.metrics[
                "total_return"
            ],
            "gates": q_gates,
            "pass": all(q_gates.values()),
        }
        if quarantine["pass"]:
            decision = "byd_v1_0_supported"

    latest_date = features.index[-1]
    latest_signals = {
        name: float(series.iloc[-1]) for name, series in candidates.items()
    }
    latest_positions = {
        name: float(full_results[name].daily["position_at_open"].iloc[-1])
        for name in CANDIDATE_NAMES
    }
    selected_latest_signal = (
        latest_signals.get(selected_name) if selected_name else None
    )
    selected_current_position = (
        latest_positions.get(selected_name) if selected_name else None
    )

    return {
        "experiment_id": str(contract["experiment_id"]),
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "selected_candidate": selected_name,
        "latest_data_date": latest_date.strftime("%Y-%m-%d"),
        "selected_latest_close_signal_for_next_open": selected_latest_signal,
        "selected_current_open_position": selected_current_position,
        "candidate_rows": rows,
        "buy_hold_selection_metrics": benchmark_selection.metrics,
        "buy_hold_validation_metrics": benchmark_validation.metrics,
        "buy_hold_quarantine_metrics": benchmark_quarantine.metrics,
        "quarantine": quarantine,
        "latest_candidate_signals": latest_signals,
        "latest_candidate_positions": latest_positions,
    }
