"""Signal and diagnostic primitives for the VIX-aware rotation experiment.

VIX is used only as a close-of-session risk-state signal. The spot index is not
traded. Portfolio preparation and execution live in ``vix_rotation_runtime`` so
there is one source of truth for MA20 features, weights, costs and next-open
execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import _return_metrics

VIX_SYMBOL = "^VIX"
STATE_TO_LABEL = {0: "defensive", 1: "attack", 2: "partial_leverage"}


@dataclass(frozen=True)
class VixRotationConfig:
    """Frozen price, VIX, portfolio and execution parameters."""

    ma_short: int = 20
    ma_medium: int = 50
    ma_long: int = 200
    ma_long_buffer: float = 0.01
    shock_drawdown: float = 0.10
    shock_lookback_sessions: int = 63
    shock_memory_sessions: int = 63
    early_breakout_sessions: int = 5
    confirmation_breakout_sessions: int = 20
    ma_rise_sessions: int = 3
    exit_below_ma_short_sessions: int = 2
    vix_rolling_window: int = 252
    vix_stress_quantile: float = 0.80
    vix_normalization_quantile: float = 0.60
    vix_spike_1d: float = 0.20
    vix_spike_5d: float = 0.35
    vix_easing_retreat_for_qqq: float = 0.15
    vix_normalization_retreat_for_tqqq: float = 0.25
    vix_falling_sessions: int = 3
    leveraged_tqqq_weight: float = 0.50
    transaction_cost_bps_per_turnover_unit: float = 10.0
    annual_risk_free_rate: float = 0.0
    charge_initial_entry: bool = True

    def __post_init__(self) -> None:
        positive_ints = {
            "ma_short": self.ma_short,
            "ma_medium": self.ma_medium,
            "ma_long": self.ma_long,
            "shock_lookback_sessions": self.shock_lookback_sessions,
            "shock_memory_sessions": self.shock_memory_sessions,
            "early_breakout_sessions": self.early_breakout_sessions,
            "confirmation_breakout_sessions": self.confirmation_breakout_sessions,
            "ma_rise_sessions": self.ma_rise_sessions,
            "exit_below_ma_short_sessions": self.exit_below_ma_short_sessions,
            "vix_rolling_window": self.vix_rolling_window,
            "vix_falling_sessions": self.vix_falling_sessions,
        }
        for name, value in positive_ints.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if not self.ma_short < self.ma_medium < self.ma_long:
            raise ValueError("moving averages must satisfy ma_short < ma_medium < ma_long")
        fractions = {
            "ma_long_buffer": self.ma_long_buffer,
            "shock_drawdown": self.shock_drawdown,
            "vix_stress_quantile": self.vix_stress_quantile,
            "vix_normalization_quantile": self.vix_normalization_quantile,
            "vix_spike_1d": self.vix_spike_1d,
            "vix_spike_5d": self.vix_spike_5d,
            "vix_easing_retreat_for_qqq": self.vix_easing_retreat_for_qqq,
            "vix_normalization_retreat_for_tqqq": self.vix_normalization_retreat_for_tqqq,
            "leveraged_tqqq_weight": self.leveraged_tqqq_weight,
        }
        for name, value in fractions.items():
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must be in (0, 1)")
        if self.vix_normalization_quantile >= self.vix_stress_quantile:
            raise ValueError("VIX normalization quantile must be below stress quantile")
        if self.transaction_cost_bps_per_turnover_unit < 0:
            raise ValueError("transaction cost must be non-negative")


def config_from_contract(contract: Mapping[str, Any]) -> VixRotationConfig:
    """Build the frozen dataclass from the versioned YAML contract."""

    price = contract["price_logic"]
    vix = contract["vix_logic"]
    portfolio = contract["portfolio"]
    return VixRotationConfig(
        ma_short=int(price["ma_short"]),
        ma_medium=int(price["ma_medium"]),
        ma_long=int(price["ma_long"]),
        ma_long_buffer=float(price["ma_long_buffer"]),
        shock_drawdown=float(price["shock_drawdown"]),
        shock_lookback_sessions=int(price["shock_lookback_sessions"]),
        shock_memory_sessions=int(price["shock_memory_sessions"]),
        early_breakout_sessions=int(price["early_breakout_sessions"]),
        confirmation_breakout_sessions=int(price["confirmation_breakout_sessions"]),
        ma_rise_sessions=int(price["ma_rise_sessions"]),
        exit_below_ma_short_sessions=int(price["exit_below_ma_short_sessions"]),
        vix_rolling_window=int(vix["rolling_window"]),
        vix_stress_quantile=float(vix["stress_quantile"]),
        vix_normalization_quantile=float(vix["normalization_quantile"]),
        vix_spike_1d=float(vix["spike_1d"]),
        vix_spike_5d=float(vix["spike_5d"]),
        vix_easing_retreat_for_qqq=float(vix["easing_retreat_for_qqq"]),
        vix_normalization_retreat_for_tqqq=float(vix["normalization_retreat_for_tqqq"]),
        vix_falling_sessions=int(vix["falling_sessions"]),
        leveraged_tqqq_weight=float(portfolio["leveraged_tqqq_weight"]),
        transaction_cost_bps_per_turnover_unit=float(
            portfolio["transaction_cost_bps_per_turnover_unit"]
        ),
        annual_risk_free_rate=float(portfolio["annual_risk_free_rate"]),
        charge_initial_entry=bool(portfolio["charge_initial_entry"]),
    )


def _normalise_close(frame: pd.DataFrame, symbol: str) -> pd.Series:
    required = {"date", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} bars missing columns: {missing}")
    out = frame[["date", "close"]].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna().query("close > 0").sort_values("date")
    if out.empty:
        raise ValueError(f"{symbol} has no usable close observations")
    if out["date"].duplicated().any():
        raise ValueError(f"{symbol} contains duplicate dates")
    return out.set_index("date")["close"].rename(symbol)


def build_vix_features(vix_bars: pd.DataFrame, config: VixRotationConfig) -> pd.DataFrame:
    """Create rolling VIX stress, retreat and normalization features."""

    close = _normalise_close(vix_bars, VIX_SYMBOL)
    features = pd.DataFrame(index=close.index)
    features["vix_close"] = close
    features["vix_return_1d"] = close.pct_change()
    features["vix_return_5d"] = close.pct_change(5)
    features["vix_ma5"] = close.rolling(5, min_periods=5).mean()
    features["vix_ma20"] = close.rolling(20, min_periods=20).mean()
    features["vix_peak_20"] = close.rolling(20, min_periods=1).max()
    features["vix_retreat_from_peak"] = close / features["vix_peak_20"] - 1.0
    minimum_quantile_history = max(60, config.vix_rolling_window // 2)
    features["vix_q_stress"] = close.rolling(
        config.vix_rolling_window,
        min_periods=minimum_quantile_history,
    ).quantile(config.vix_stress_quantile)
    features["vix_q_normal"] = close.rolling(
        config.vix_rolling_window,
        min_periods=minimum_quantile_history,
    ).quantile(config.vix_normalization_quantile)
    features["vix_falling"] = (
        close.diff()
        .lt(0)
        .rolling(
            config.vix_falling_sessions,
            min_periods=config.vix_falling_sessions,
        )
        .sum()
        .eq(config.vix_falling_sessions)
    )
    features["vix_stress"] = (
        close.ge(features["vix_q_stress"])
        | features["vix_return_1d"].ge(config.vix_spike_1d)
        | features["vix_return_5d"].ge(config.vix_spike_5d)
    ).fillna(False)
    features["vix_easing"] = (
        features["vix_falling"]
        | features["vix_retreat_from_peak"].le(-config.vix_easing_retreat_for_qqq)
    ).fillna(False)
    features["vix_normalized"] = (
        (
            close.le(features["vix_q_normal"])
            | features["vix_retreat_from_peak"].le(-config.vix_normalization_retreat_for_tqqq)
        )
        & close.lt(features["vix_ma20"])
        & ~features["vix_stress"]
    ).fillna(False)
    features["vix_regime"] = "normal"
    features.loc[features["vix_stress"], "vix_regime"] = "stress"
    calm = close.le(features["vix_q_normal"]) & close.lt(features["vix_ma20"])
    features.loc[calm.fillna(False), "vix_regime"] = "calm"
    return features


def generate_vix_decision_states(prepared: pd.DataFrame, config: VixRotationConfig) -> pd.DataFrame:
    """Generate close-decided states for next-open execution."""

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
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_ma50_vix_normalized"
        else:
            if bool(row.vix_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_or_ma20"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons},
        index=prepared.index,
    )


def vix_regime_asset_metrics(prepared: pd.DataFrame) -> pd.DataFrame:
    """Compare next-open QQQI and QQQ outcomes after each VIX regime close."""

    rows: list[dict[str, Any]] = []
    for regime in ("calm", "normal", "stress"):
        mask = prepared["vix_regime"].shift(1).eq(regime)
        for symbol in ("QQQI", "QQQ"):
            series = prepared.loc[mask, f"{symbol}_next_open_return"].dropna()
            metrics = _return_metrics(series)
            rows.append(
                {
                    "vix_regime": regime,
                    "symbol": symbol,
                    "sessions": int(len(series)),
                    "cumulative_return": metrics["total_return"],
                    "annualized_volatility": metrics["annual_volatility"],
                    "sharpe": metrics["sharpe"],
                    "max_drawdown": metrics["max_drawdown"],
                }
            )
    return pd.DataFrame(rows).set_index(["vix_regime", "symbol"])


def vix_repair_event_study(
    prepared: pd.DataFrame,
    *,
    horizons: Sequence[int] = (5, 10, 20, 40),
    cluster_gap_sessions: int = 20,
) -> pd.DataFrame:
    """Study QQQ versus QQQI after VIX stress begins, eases and normalizes."""

    if not horizons or min(horizons) <= 0:
        raise ValueError("horizons must contain positive values")
    if cluster_gap_sessions <= 0:
        raise ValueError("cluster_gap_sessions must be positive")

    previous_stress = prepared["vix_stress"].shift(1).fillna(False).astype(bool)
    stress_start = prepared["vix_stress"] & ~previous_stress
    clusters: list[tuple[int, int]] = []
    cluster_id = -1
    last_start = -10_000
    for location in np.flatnonzero(stress_start.to_numpy(dtype=bool)):
        if int(location) - last_start > cluster_gap_sessions:
            cluster_id += 1
            clusters.append((cluster_id, int(location)))
        last_start = int(location)

    rows: list[dict[str, Any]] = []
    max_horizon = max(horizons)
    event_specs = {
        "vix_stress_start": prepared["vix_stress"],
        "vix_easing": prepared["vix_easing"],
        "vix_normalized": prepared["vix_normalized"],
    }
    for current_cluster, stress_location in clusters:
        stop = min(len(prepared), stress_location + 64)
        cluster_slice = prepared.iloc[stress_location:stop]
        for event_name, event_mask in event_specs.items():
            if event_name == "vix_stress_start":
                event_location = stress_location
            else:
                local_mask = event_mask.reindex(cluster_slice.index).fillna(False)
                matches = np.flatnonzero(local_mask.to_numpy(dtype=bool))
                if len(matches) == 0:
                    continue
                event_location = stress_location + int(matches[0])
            event_date = prepared.index[event_location]
            entry_location = event_location + 1
            if entry_location >= len(prepared):
                continue
            row: dict[str, Any] = {
                "cluster_id": current_cluster,
                "stress_date": prepared.index[stress_location],
                "event": event_name,
                "event_date": event_date,
                "entry_date": prepared.index[entry_location],
                "sessions_after_stress": int(event_location - stress_location),
                "vix_at_event": float(prepared.iloc[event_location]["vix_close"]),
            }
            for horizon in horizons:
                window = prepared.iloc[entry_location : entry_location + horizon]
                for symbol in ("QQQI", "QQQ"):
                    values = window[f"{symbol}_next_open_return"].dropna()
                    value = np.nan
                    if len(values) == horizon:
                        value = float((1.0 + values).prod() - 1.0)
                    row[f"{symbol}_return_{horizon}d"] = value
                row[f"QQQ_minus_QQQI_{horizon}d"] = (
                    row[f"QQQ_return_{horizon}d"] - row[f"QQQI_return_{horizon}d"]
                )
            risk_window = prepared.iloc[entry_location : entry_location + max_horizon]
            for symbol in ("QQQI", "QQQ"):
                values = risk_window[f"{symbol}_next_open_return"].dropna()
                if values.empty:
                    row[f"{symbol}_max_adverse_{max_horizon}d"] = np.nan
                else:
                    path = (1.0 + values).cumprod() - 1.0
                    row[f"{symbol}_max_adverse_{max_horizon}d"] = float(path.min())
            rows.append(row)
    return pd.DataFrame(rows)


def vix_signal_audit(
    prepared: pd.DataFrame,
    config: VixRotationConfig | None = None,
) -> dict[str, Any]:
    """Summarise whether VIX gates and all v2 states were exercised."""

    effective_config = config or VixRotationConfig()
    decisions = generate_vix_decision_states(prepared, effective_config)
    counts = decisions["decision_state"].value_counts().reindex([0, 1, 2], fill_value=0)
    return {
        "observations": int(len(prepared)),
        "vix_stress_sessions": int(prepared["vix_stress"].sum()),
        "vix_easing_sessions": int(prepared["vix_easing"].sum()),
        "vix_normalized_sessions": int(prepared["vix_normalized"].sum()),
        "decision_state_counts": {
            STATE_TO_LABEL[state]: int(counts.loc[state]) for state in (0, 1, 2)
        },
        "all_states_reached": bool((counts > 0).all()),
    }
