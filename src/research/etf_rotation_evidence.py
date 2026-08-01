"""Evidence governance helpers for the ETF rotation experiment.

These diagnostics distinguish stable performance from a structurally inactive
state machine. A grid can look insensitive simply because one state or one
parameter never affects any decision; that is not robustness.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import (
    REQUIRED_SYMBOLS,
    STATE_TO_LABEL,
    STATE_TO_SYMBOL,
    RotationConfig,
    StrategyResult,
    _normalise_bars,
    _return_metrics,
    build_signal_frame,
    generate_decision_states,
)


def state_reachability_summary(result: StrategyResult) -> dict[str, Any]:
    """Report whether every intended portfolio state was actually executed."""

    daily = result.daily
    state_rows: list[dict[str, Any]] = []
    for state, symbol in STATE_TO_SYMBOL.items():
        sessions = int(daily["position_state"].eq(state).sum())
        state_rows.append(
            {
                "state": state,
                "label": STATE_TO_LABEL[state],
                "symbol": symbol,
                "sessions": sessions,
                "share": float(sessions / len(daily)) if len(daily) else np.nan,
                "reached": bool(sessions > 0),
            }
        )
    signal_counts = {
        name: int(daily[name].fillna(False).astype(bool).sum())
        for name in ("enter_attack", "enter_leveraged", "defensive_break", "exit_leveraged")
        if name in daily.columns
    }
    unreachable = [row["symbol"] for row in state_rows if not row["reached"]]
    return {
        "strategy": result.metrics.get("strategy", result.name),
        "observations": int(len(daily)),
        "states": state_rows,
        "signal_counts": signal_counts,
        "all_intended_states_reached": not unreachable,
        "unreachable_symbols": unreachable,
        "structurally_complete": not unreachable,
        "note": (
            "An unreachable intended state makes risk/return sensitivity for that state "
            "and its exit parameters uninterpretable."
        ),
    }


def parameter_activity_audit(
    grid_results: pd.DataFrame,
    *,
    parameter_columns: Sequence[str],
    outcome_columns: Sequence[str] = (
        "cagr",
        "max_drawdown",
        "calmar",
        "sharpe",
        "switch_count",
        "pct_time_qqqi",
        "pct_time_qqq",
        "pct_time_tqqq",
    ),
) -> pd.DataFrame:
    """Detect parameters that never change decisions or outcomes.

    For each parameter, matched groups hold every other parameter fixed. The
    parameter is active only if changing it alters at least one declared outcome
    in at least one matched group.
    """

    params = list(parameter_columns)
    missing = sorted(set(params).difference(grid_results.columns))
    if missing:
        raise ValueError(f"grid results missing parameter columns: {missing}")
    outcomes = [column for column in outcome_columns if column in grid_results.columns]
    if not outcomes:
        raise ValueError("grid results contain none of the requested outcome columns")

    rows: list[dict[str, Any]] = []
    for parameter in params:
        others = [column for column in params if column != parameter]
        grouped = (
            grid_results.groupby(others, dropna=False, sort=False)
            if others
            else [((), grid_results)]
        )
        matched_groups = 0
        changed_groups = 0
        changed_outcomes: set[str] = set()
        for _, group in grouped:
            if group[parameter].nunique(dropna=False) <= 1:
                continue
            matched_groups += 1
            local_changes = [
                outcome
                for outcome in outcomes
                if group[outcome].nunique(dropna=False) > 1
            ]
            if local_changes:
                changed_groups += 1
                changed_outcomes.update(local_changes)
        rows.append(
            {
                "parameter": parameter,
                "matched_groups": matched_groups,
                "changed_groups": changed_groups,
                "changed_group_share": (
                    float(changed_groups / matched_groups) if matched_groups else np.nan
                ),
                "active": bool(changed_groups > 0),
                "changed_outcomes": ",".join(sorted(changed_outcomes)),
            }
        )
    return pd.DataFrame(rows).set_index("parameter")


def long_history_asset_context(
    bars: Mapping[str, pd.DataFrame],
    periods: Mapping[str, tuple[str, str]],
    *,
    symbols: Sequence[str] = ("QQQ", "TQQQ"),
    annual_risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Return proxy-free QQQ/TQQQ context outside QQQI's live history.

    This is descriptive context only. It must not be presented as a backtest of
    the three-asset strategy because QQQI did not exist in the earlier periods.
    """

    selected = [str(symbol).upper() for symbol in symbols]
    invalid = sorted(set(selected).difference(REQUIRED_SYMBOLS))
    if invalid:
        raise ValueError(f"unsupported symbols: {invalid}")
    normalised = {symbol: _normalise_bars(bars[symbol], symbol) for symbol in selected}
    common_index = normalised[selected[0]].index
    for symbol in selected[1:]:
        common_index = common_index.intersection(normalised[symbol].index)
    common_index = common_index.sort_values()
    returns = pd.DataFrame(index=common_index)
    for symbol in selected:
        open_price = normalised[symbol].reindex(common_index)["open"]
        returns[symbol] = open_price.shift(-1) / open_price - 1.0

    scopes = {
        "full_qqq_tqqq_common_history": (
            str(common_index.min().date()),
            str(common_index.max().date()),
        )
    }
    scopes.update(periods)
    rows: list[dict[str, Any]] = []
    for scope, (start, end) in scopes.items():
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        for symbol in selected:
            series = returns.loc[start_ts:end_ts, symbol].dropna()
            metrics = _return_metrics(series, annual_risk_free_rate=annual_risk_free_rate)
            rows.append(
                {
                    "scope": scope,
                    "symbol": symbol,
                    "context_only": True,
                    **metrics,
                }
            )
    return pd.DataFrame(rows).set_index(["scope", "symbol"])


def long_history_signal_audit(
    qqq_bars: pd.DataFrame,
    config: RotationConfig,
    periods: Mapping[str, tuple[str, str]],
    *,
    version: str = "B",
) -> pd.DataFrame:
    """Audit state requests over full QQQ history without inventing QQQI returns."""

    signal = build_signal_frame(qqq_bars, config)
    signal = signal[signal["ma_long"].notna() & signal["ma_short"].notna()].copy()
    decisions = generate_decision_states(signal, config, version=version)
    audit = signal.join(decisions)
    scopes = {
        "full_qqq_signal_history": (
            str(audit.index.min().date()),
            str(audit.index.max().date()),
        )
    }
    scopes.update(periods)
    rows: list[dict[str, Any]] = []
    for scope, (start, end) in scopes.items():
        sample = audit.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        for state, symbol in STATE_TO_SYMBOL.items():
            sessions = int(sample["decision_state"].eq(state).sum())
            rows.append(
                {
                    "scope": scope,
                    "state": state,
                    "symbol": symbol,
                    "sessions": sessions,
                    "share": float(sessions / len(sample)) if len(sample) else np.nan,
                    "signal_only": True,
                    "qqqi_tradability_not_assumed": True,
                }
            )
    return pd.DataFrame(rows).set_index(["scope", "state"])
