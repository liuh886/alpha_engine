"""Post-v4 VXN veto limited to the 75% TQQQ risk layer."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.breadth_vxn_rotation_experiment import VXN_SYMBOL, build_vxn_features
from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import VIX_SYMBOL, VixRotationConfig, config_from_contract, generate_vix_decision_states
from src.research.vix_rotation_runtime import (
    _run_weighted_state_backtest,
    prepare_vix_rotation_runtime_data,
    run_vix_runtime_comparison,
    state_reachability,
)


def prepare_vxn_overlay_data(
    bars: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]
) -> tuple[pd.DataFrame, VixRotationConfig]:
    required = {"QQQI", "QQQ", "TQQQ", VIX_SYMBOL, VXN_SYMBOL}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")
    config = config_from_contract(contract)
    prepared = prepare_vix_rotation_runtime_data(bars, config)
    vxn = build_vxn_features(bars[VXN_SYMBOL], config)
    out = prepared.join(vxn, how="left")
    for column in ("vxn_falling", "vxn_stress", "vxn_easing", "vxn_normalized"):
        out[column] = out[column].fillna(False).astype(bool)
    out["vxn_regime"] = out["vxn_regime"].fillna("unavailable")
    out = out.dropna(subset=["vxn_close", "vxn_q_stress", "vxn_q_normal"]).copy()
    if len(out) < 40:
        raise ValueError("VXN overlay common sample is too short")
    return out, config


def generate_vxn_leverage_veto_states(
    prepared: pd.DataFrame, config: VixRotationConfig
) -> pd.DataFrame:
    """Keep VIX v3 states except veto or exit partial leverage on VXN stress."""

    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for row in prepared.itertuples():
        next_state = state
        reason = "hold"
        severe_defense = bool(row.long_break) or (
            bool(row.vix_stress) and bool(row.stress_price_failure)
        )
        if severe_defense:
            next_state = 0
            reason = "defensive_price_or_vix_stress"
        elif state == 0:
            if bool(row.shock_memory) and bool(row.early_repair) and bool(row.vix_easing):
                next_state = 1
                reason = "enter_qqq_early_repair_vix_easing"
        elif state == 1:
            leverage_ready = (
                bool(row.shock_memory)
                and bool(row.medium_repair)
                and bool(row.secondary_confirmation)
                and bool(row.vix_normalized)
                and not bool(row.vxn_stress)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_vix_normalized_vxn_not_stressed"
        else:
            if bool(row.vix_stress) or bool(row.vxn_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_vxn_or_ma20"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons}, index=prepared.index
    )


def _capture(result: StrategyResult) -> dict[str, float | int]:
    returns = result.daily.loc[result.daily["position_state"].eq(2), "net_return"].dropna()
    if returns.empty:
        return {"sessions": 0, "cumulative_net_return": 0.0, "worst_daily_net_return": 0.0}
    return {
        "sessions": int(len(returns)),
        "cumulative_net_return": float((1.0 + returns).prod() - 1.0),
        "mean_daily_net_return": float(returns.mean()),
        "positive_session_rate": float(returns.gt(0).mean()),
        "worst_daily_net_return": float(returns.min()),
    }


def _blocked_entries(
    prepared: pd.DataFrame,
    baseline: pd.DataFrame,
    challenger: pd.DataFrame,
    horizons: Sequence[int],
) -> list[dict[str, Any]]:
    previous = baseline["decision_state"].shift(1).fillna(0).astype(int)
    mask = baseline["decision_state"].eq(2) & previous.ne(2) & challenger["decision_state"].ne(2)
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(mask.to_numpy(dtype=bool)):
        row: dict[str, Any] = {
            "signal_date": prepared.index[int(location)],
            "vix_normalized": bool(prepared.iloc[int(location)]["vix_normalized"]),
            "vxn_stress": bool(prepared.iloc[int(location)]["vxn_stress"]),
            "vix_close": float(prepared.iloc[int(location)]["vix_close"]),
            "vxn_close": float(prepared.iloc[int(location)]["vxn_close"]),
        }
        for horizon in horizons:
            window = prepared.iloc[int(location) + 1 : int(location) + 1 + int(horizon)]
            values = window["TQQQ_next_open_return"].dropna()
            row[f"TQQQ_return_{horizon}d"] = (
                float((1.0 + values).prod() - 1.0)
                if len(values) == int(horizon)
                else np.nan
            )
        rows.append(row)
    return rows


def run_vxn_leverage_overlay_comparison(
    bars: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame, dict[str, Any]]:
    prepared, config = prepare_vxn_overlay_data(bars, contract)
    _, base_results, _ = run_vix_runtime_comparison(bars, config)
    baseline_decisions = generate_vix_decision_states(prepared, config)
    overlay_decisions = generate_vxn_leverage_veto_states(prepared, config)

    baseline = _run_weighted_state_backtest(
        prepared,
        config,
        baseline_decisions,
        strategy_key="rotation_vix_v3_75",
        display_name="VIX v3, 75% TQQQ",
    )
    overlay = _run_weighted_state_backtest(
        prepared,
        config,
        overlay_decisions,
        strategy_key="rotation_vxn_leverage_v4_1_75",
        display_name="VIX v3 + VXN leverage veto, 75% TQQQ",
    )
    buy_hold = base_results["buy_hold_QQQ"]
    buy_hold.metrics["strategy"] = "buy_hold_QQQ"
    results = {
        "buy_hold_QQQ": buy_hold,
        "rotation_vix_v3_75": baseline,
        "rotation_vxn_leverage_v4_1_75": overlay,
    }
    metrics = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    horizons = [int(value) for value in contract["validation"]["event_horizons"]]
    diagnostics = {
        "post_result_hypothesis": True,
        "vxn_role": "partial_leverage_veto_only",
        "state_reachability": {
            "baseline": state_reachability(baseline),
            "overlay": state_reachability(overlay),
        },
        "leverage_capture": {
            "baseline": _capture(baseline),
            "overlay": _capture(overlay),
        },
        "blocked_baseline_entries": _blocked_entries(
            prepared, baseline_decisions, overlay_decisions, horizons
        ),
        "same_defensive_rule": True,
        "same_initial_qqq_rule": True,
    }
    return metrics.sort_index(), results, prepared, diagnostics
