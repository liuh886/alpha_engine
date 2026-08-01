"""Market-breadth and VXN challengers for the frozen QQQ recovery strategy.

The module deliberately tests two independent information additions:

* ``QQQE / QQQ`` as a survivorship-resistant Nasdaq-100 breadth proxy;
* ``VXN`` as Nasdaq-100-specific expected volatility.

Price repair, next-open execution, costs and the 75% TQQQ risk budget are
inherited from the frozen VIX v3 contract.  No function places orders or marks
an experiment trade-ready.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import (
    VIX_SYMBOL,
    VixRotationConfig,
    _normalise_close,
    build_vix_features,
    config_from_contract,
    generate_vix_decision_states,
)
from src.research.vix_rotation_runtime import (
    _run_weighted_state_backtest,
    prepare_vix_rotation_runtime_data,
    run_vix_runtime_comparison,
    state_reachability,
)

BREADTH_SYMBOL = "QQQE"
VXN_SYMBOL = "^VXN"


def build_breadth_features(
    breadth_bars: pd.DataFrame,
    qqq_bars: pd.DataFrame,
    *,
    ratio_ma_window: int,
    momentum_sessions: int,
) -> pd.DataFrame:
    """Build an equal-weight versus cap-weight Nasdaq-100 breadth proxy."""

    if ratio_ma_window <= 1 or momentum_sessions <= 0:
        raise ValueError("breadth windows must be positive")
    qqqe = _normalise_close(breadth_bars, BREADTH_SYMBOL)
    qqq = _normalise_close(qqq_bars, "QQQ")
    aligned = pd.concat([qqqe.rename("qqqe_close"), qqq.rename("qqq_close")], axis=1)
    aligned = aligned.dropna()
    features = pd.DataFrame(index=aligned.index)
    features["qqqe_qqq_ratio"] = aligned["qqqe_close"] / aligned["qqq_close"]
    features["breadth_ratio_ma"] = features["qqqe_qqq_ratio"].rolling(
        ratio_ma_window,
        min_periods=ratio_ma_window,
    ).mean()
    features["breadth_ratio_momentum"] = features["qqqe_qqq_ratio"].pct_change(
        momentum_sessions
    )
    features["breadth_above_ma"] = features["qqqe_qqq_ratio"].gt(
        features["breadth_ratio_ma"]
    )
    features["breadth_positive_momentum"] = features["breadth_ratio_momentum"].gt(0.0)
    features["breadth_confirmed"] = (
        features["breadth_above_ma"] & features["breadth_positive_momentum"]
    ).fillna(False)
    features["breadth_regime"] = "mixed"
    features.loc[features["breadth_confirmed"], "breadth_regime"] = "broadening"
    narrowing = (
        ~features["breadth_above_ma"].fillna(False)
        & ~features["breadth_positive_momentum"].fillna(False)
    )
    features.loc[narrowing, "breadth_regime"] = "narrowing"
    return features


def build_vxn_features(vxn_bars: pd.DataFrame, config: VixRotationConfig) -> pd.DataFrame:
    """Apply the frozen dynamic VIX feature contract to VXN observations."""

    raw = build_vix_features(vxn_bars, config)
    return raw.rename(columns={column: column.replace("vix_", "vxn_") for column in raw})


def prepare_breadth_vxn_data(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, VixRotationConfig]:
    """Join the frozen VIX runtime frame with breadth and VXN features."""

    required = {"QQQI", "QQQ", "TQQQ", VIX_SYMBOL, BREADTH_SYMBOL, VXN_SYMBOL}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")
    config = config_from_contract(contract)
    prepared = prepare_vix_rotation_runtime_data(bars, config)
    breadth_logic = contract["breadth_logic"]
    breadth = build_breadth_features(
        bars[BREADTH_SYMBOL],
        bars["QQQ"],
        ratio_ma_window=int(breadth_logic["ratio_ma_window"]),
        momentum_sessions=int(breadth_logic["ratio_momentum_sessions"]),
    )
    vxn = build_vxn_features(bars[VXN_SYMBOL], config)
    out = prepared.join(breadth, how="left").join(vxn, how="left")
    bool_columns = [
        "breadth_above_ma",
        "breadth_positive_momentum",
        "breadth_confirmed",
        "vxn_falling",
        "vxn_stress",
        "vxn_easing",
        "vxn_normalized",
    ]
    for column in bool_columns:
        out[column] = out[column].fillna(False).astype(bool)
    out["breadth_regime"] = out["breadth_regime"].fillna("unavailable")
    out["vxn_regime"] = out["vxn_regime"].fillna("unavailable")
    out = out.dropna(
        subset=[
            "qqqe_qqq_ratio",
            "breadth_ratio_ma",
            "vxn_close",
            "vxn_q_stress",
            "vxn_q_normal",
        ]
    ).copy()
    if len(out) < 40:
        raise ValueError("breadth/VXN common sample is too short")
    return out, config


def _decision_frame(states: list[int], reasons: list[str], index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons},
        index=index,
    )


def generate_breadth_decision_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
) -> pd.DataFrame:
    """Gate only the VIX-v3 partial-leverage entry with market breadth."""

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
                and bool(row.breadth_confirmed)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_vix_and_breadth_confirmed"
        else:
            if bool(row.vix_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_or_ma20"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return _decision_frame(states, reasons, prepared.index)


def generate_vxn_only_decision_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
) -> pd.DataFrame:
    """Replace VIX states with VXN while preserving every price rule."""

    proxy = prepared.copy()
    for suffix in ("stress", "easing", "normalized"):
        proxy[f"vix_{suffix}"] = proxy[f"vxn_{suffix}"]
    decisions = generate_vix_decision_states(proxy, config)
    decisions["decision_reason"] = decisions["decision_reason"].str.replace(
        "vix", "vxn", regex=False
    )
    return decisions


def generate_dual_volatility_decision_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
) -> pd.DataFrame:
    """Require VIX and VXN confirmation; either index can force risk reduction."""

    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for row in prepared.itertuples():
        next_state = state
        reason = "hold"
        either_stress = bool(row.vix_stress) or bool(row.vxn_stress)
        severe_defense = bool(row.long_break) or (
            either_stress and bool(row.stress_price_failure)
        )
        if severe_defense:
            next_state = 0
            reason = "defensive_price_or_vix_vxn_stress"
        elif state == 0:
            if (
                bool(row.shock_memory)
                and bool(row.early_repair)
                and bool(row.vix_easing)
                and bool(row.vxn_easing)
            ):
                next_state = 1
                reason = "enter_qqq_vix_vxn_easing"
        elif state == 1:
            leverage_ready = (
                bool(row.shock_memory)
                and bool(row.medium_repair)
                and bool(row.secondary_confirmation)
                and bool(row.vix_normalized)
                and bool(row.vxn_normalized)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_vix_vxn_normalized"
        else:
            if either_stress or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_vxn_or_ma20"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return _decision_frame(states, reasons, prepared.index)


def _rename_result(result: StrategyResult, strategy: str, display_name: str) -> StrategyResult:
    result.name = display_name
    result.metrics["strategy"] = strategy
    return result


def _leverage_capture(result: StrategyResult) -> dict[str, float | int]:
    returns = result.daily.loc[result.daily["position_state"].eq(2), "net_return"].dropna()
    if returns.empty:
        return {
            "sessions": 0,
            "cumulative_net_return": 0.0,
            "mean_daily_net_return": 0.0,
            "positive_session_rate": 0.0,
            "worst_daily_net_return": 0.0,
        }
    return {
        "sessions": int(len(returns)),
        "cumulative_net_return": float((1.0 + returns).prod() - 1.0),
        "mean_daily_net_return": float(returns.mean()),
        "positive_session_rate": float(returns.gt(0).mean()),
        "worst_daily_net_return": float(returns.min()),
    }


def _blocked_entry_outcomes(
    prepared: pd.DataFrame,
    baseline: pd.DataFrame,
    challenger: pd.DataFrame,
    horizons: Sequence[int],
) -> list[dict[str, Any]]:
    previous = baseline["decision_state"].shift(1).fillna(0).astype(int)
    blocked = (
        baseline["decision_state"].eq(2)
        & previous.ne(2)
        & challenger["decision_state"].ne(2)
    )
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(blocked.to_numpy(dtype=bool)):
        row: dict[str, Any] = {
            "signal_date": prepared.index[int(location)],
            "breadth_confirmed": bool(prepared.iloc[int(location)]["breadth_confirmed"]),
            "vix_normalized": bool(prepared.iloc[int(location)]["vix_normalized"]),
            "vxn_normalized": bool(prepared.iloc[int(location)]["vxn_normalized"]),
        }
        for horizon in horizons:
            window = prepared.iloc[int(location) + 1 : int(location) + 1 + int(horizon)]
            for symbol in ("QQQ", "TQQQ"):
                values = window[f"{symbol}_next_open_return"].dropna()
                row[f"{symbol}_return_{horizon}d"] = (
                    float((1.0 + values).prod() - 1.0)
                    if len(values) == int(horizon)
                    else np.nan
                )
        rows.append(row)
    return rows


def _volatility_overlap(prepared: pd.DataFrame) -> dict[str, Any]:
    returns = prepared[["vix_return_1d", "vxn_return_1d"]].dropna()
    output: dict[str, Any] = {
        "level_correlation": float(
            prepared[["vix_close", "vxn_close"]].dropna().corr().iloc[0, 1]
        ),
        "daily_change_correlation": float(returns.corr().iloc[0, 1]),
    }
    for state in ("stress", "easing", "normalized"):
        vix = prepared[f"vix_{state}"].astype(bool)
        vxn = prepared[f"vxn_{state}"].astype(bool)
        output[state] = {
            "vix_sessions": int(vix.sum()),
            "vxn_sessions": int(vxn.sum()),
            "both_sessions": int((vix & vxn).sum()),
            "vix_only_sessions": int((vix & ~vxn).sum()),
            "vxn_only_sessions": int((vxn & ~vix).sum()),
        }
    return output


def run_breadth_vxn_comparison(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame, dict[str, Any]]:
    """Run separate breadth, VXN-only and VIX+VXN challengers."""

    prepared, config = prepare_breadth_vxn_data(bars, contract)
    _, baseline_results, baseline_prepared = run_vix_runtime_comparison(bars, config)
    baseline_prepared = baseline_prepared.reindex(prepared.index)
    pd.testing.assert_index_equal(prepared.index, baseline_prepared.index)

    baseline_decisions = generate_vix_decision_states(prepared, config)
    breadth_decisions = generate_breadth_decision_states(prepared, config)
    vxn_decisions = generate_vxn_only_decision_states(prepared, config)
    dual_decisions = generate_dual_volatility_decision_states(prepared, config)

    baseline = _run_weighted_state_backtest(
        prepared,
        config,
        baseline_decisions,
        strategy_key="rotation_vix_v3_75",
        display_name="VIX v3, 75% TQQQ",
    )
    breadth = _run_weighted_state_backtest(
        prepared,
        config,
        breadth_decisions,
        strategy_key="rotation_breadth_v4_75",
        display_name="VIX v3 + breadth gate, 75% TQQQ",
    )
    vxn = _run_weighted_state_backtest(
        prepared,
        config,
        vxn_decisions,
        strategy_key="rotation_vxn_only_v4_75",
        display_name="VXN-only v4, 75% TQQQ",
    )
    dual = _run_weighted_state_backtest(
        prepared,
        config,
        dual_decisions,
        strategy_key="rotation_vix_vxn_confirm_v4_75",
        display_name="VIX + VXN confirmation v4, 75% TQQQ",
    )
    buy_hold = _rename_result(
        baseline_results["buy_hold_QQQ"],
        "buy_hold_QQQ",
        "QQQ buy and hold",
    )
    results = {
        "buy_hold_QQQ": buy_hold,
        "rotation_vix_v3_75": baseline,
        "rotation_breadth_v4_75": breadth,
        "rotation_vxn_only_v4_75": vxn,
        "rotation_vix_vxn_confirm_v4_75": dual,
    }
    metrics = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    horizons = [int(value) for value in contract["validation"]["event_horizons"]]
    diagnostics = {
        "breadth_proxy": "QQQE/QQQ",
        "volatility_overlap": _volatility_overlap(prepared),
        "state_reachability": {
            key: state_reachability(result)
            for key, result in results.items()
            if key != "buy_hold_QQQ"
        },
        "leverage_capture": {
            key: _leverage_capture(result)
            for key, result in results.items()
            if key != "buy_hold_QQQ"
        },
        "blocked_baseline_leverage_entries": {
            "breadth": _blocked_entry_outcomes(
                prepared,
                baseline_decisions,
                breadth_decisions,
                horizons,
            ),
            "vxn_only": _blocked_entry_outcomes(
                prepared,
                baseline_decisions,
                vxn_decisions,
                horizons,
            ),
            "dual_confirmation": _blocked_entry_outcomes(
                prepared,
                baseline_decisions,
                dual_decisions,
                horizons,
            ),
        },
    }
    return metrics.sort_index(), results, prepared, diagnostics
