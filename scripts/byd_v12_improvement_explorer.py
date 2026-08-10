"""BYD V1.2 Systematic Improvement Exploration.

Tests EVERY possible improvement angle on V1.2:
  1. Regime-adaptive core position (Bull/Bear/Sideways)
  2. Drawdown-scaled core
  3. Vol-adaptive momentum thresholds
  4. Momentum threshold divisor sensitivity
  5. Exit condition variations
  6. Min-hold on V1.2 state changes
  7. 515180.SH dynamic allocation
  8. Entry condition sensitivity
  9. Combined best improvements
  10. SMA window variations
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)

CANONICAL_ROOT = PROJECT_ROOT / "data" / "research" / "byd_canonical_v1_extracted"
OUTPUT_BASE = PROJECT_ROOT / "data" / "research" / "byd_v2_experiments"
COST_BPS = 20.0  # V1.2 uses 20bps
FINANCING_RATE = 0.06  # V1.2 uses 6%

# — Shared utilities —————————————————————————————————————————————————————


def compute_metrics(returns: pd.Series) -> dict[str, float]:
    clean = returns.dropna()
    if clean.empty:
        return {"cagr": 0, "sharpe": 0, "max_drawdown": 0, "calmar": 0}
    years = len(clean) / 252.0
    wealth = (1.0 + clean).cumprod()
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and wealth.iloc[-1] > 0 else -1.0
    vol = float(clean.std(ddof=0) * np.sqrt(252.0))
    sharpe = float(clean.mean() / clean.std(ddof=0) * np.sqrt(252.0)) if clean.std(ddof=0) > 0 else 0.0
    max_dd = float((wealth / wealth.cummax() - 1.0).min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": max_dd, "calmar": calmar,
            "total_return": float(wealth.iloc[-1] - 1.0), "years": years,
            "annual_volatility": vol}


def _stateful_hysteresis(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """V1.0-style asymmetric hysteresis: harder to exit than enter."""
    active = False
    values: list[float] = []
    for e, x in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(x):
            active = False
        elif not active and bool(e):
            active = True
        values.append(1.0 if active else 0.0)
    return pd.Series(values, index=entry.index, dtype=float)


def _stateful_min_hold(entry: pd.Series, exit_: pd.Series, min_hold: int) -> pd.Series:
    active = False
    counter = 0
    values: list[float] = []
    for e, x in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active:
            counter += 1
        if active and bool(x) and counter >= min_hold:
            active = False
            counter = 0
        elif not active and bool(e):
            active = True
            counter = 0
        values.append(1.0 if active else 0.0)
    return pd.Series(values, index=entry.index, dtype=float)


# — V1.2 Baseline Reimplementation ———————————————————————————————————————


def compute_v12_state(frame: pd.DataFrame,
                      sma_short: int = 60,
                      sma_long: int = 200,
                      vol_window: int = 60,
                      dd_window: int = 252,
                      mom_divisor: float = 0.15,
                      convex_power: float = 4.0,
                      expansion_pct: float = 0.125,
                      defense_byd: float = 0.75,
                      ) -> pd.DataFrame:
    """Reimplement V1.2 convex momentum budget logic exactly.

    Returns DataFrame with columns: base_byd_weight, expansion_active, byd_weight, etf_weight
    """
    close = frame["close"]
    sma_l = close.rolling(sma_long, min_periods=sma_long).mean()
    sma_s = close.rolling(sma_short, min_periods=sma_short).mean()

    # Market state
    bull = close.gt(sma_l) & sma_s.gt(sma_l)
    close.lt(sma_l) & sma_s.lt(sma_l)

    # Vol state
    daily_ret = close.pct_change()
    realized_vol = daily_ret.rolling(vol_window).std()
    vol_median = realized_vol.rolling(756, min_periods=252).median().shift(1)
    high_vol = realized_vol > vol_median

    # Momentum
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)

    # Drawdown
    high_dd = close.rolling(dd_window, min_periods=dd_window).max()
    drawdown = close / high_dd - 1.0

    # — V1.0 core position logic ———————————————————————————————————————
    # Risk-on entry: close > sma_120 AND mom_20 > 0
    sma_120 = close.rolling(120, min_periods=120).mean()
    risk_on_entry = close.gt(sma_120) & mom_20.gt(0.0)
    risk_off_exit = close.lt(sma_120) & mom_60.lt(0.0)

    base_risk_on = _stateful_hysteresis(risk_on_entry, risk_off_exit)

    # Base BYD weight: 1.0 when risk-on, defense_byd when risk-off
    base_byd_weight = pd.Series(np.where(base_risk_on > 0.5, 1.0, defense_byd), index=frame.index)

    # — V1.2 trend expansion ———————————————————————————————————————————
    # Entry: base == 1.0, bull, low vol, mom_20 > 0, mom_60 > 0, drawdown > -10%
    expansion_entry = (
        (base_byd_weight >= 1.0) &
        bull &
        (~high_vol) &
        mom_20.gt(0.0) &
        mom_60.gt(0.0) &
        drawdown.gt(-0.10)
    )
    # Exit: base == defense_byd OR not bull OR high vol OR mom_20 <= 0
    expansion_exit = (
        (base_byd_weight <= defense_byd + 0.01) |
        (~bull) |
        high_vol |
        mom_20.le(0.0)
    )

    expansion_active = _stateful_hysteresis(expansion_entry, expansion_exit)

    # Convex momentum scale
    mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / mom_divisor) ** convex_power
    expansion_increment = mom_scale * expansion_pct

    # Final BYD weight
    byd_weight = base_byd_weight.copy()
    financed_sessions = expansion_active > 0.5
    byd_weight.loc[financed_sessions] = 1.0 + expansion_increment.loc[financed_sessions]
    byd_weight = byd_weight.clip(upper=1.0 + expansion_pct)

    # ETF weight: 25% when in defense, 0% when risk-on or expansion
    etf_weight = pd.Series(0.0, index=frame.index)
    defense_mask = (base_byd_weight <= defense_byd + 0.01) & (~financed_sessions)
    etf_weight.loc[defense_mask] = 1.0 - defense_byd

    return pd.DataFrame({
        "base_risk_on": base_risk_on,
        "base_byd_weight": base_byd_weight,
        "expansion_active": expansion_active.astype(float),
        "byd_weight": byd_weight,
        "etf_weight": etf_weight,
        "financed_sessions": financed_sessions.astype(float),
        "bull": bull.astype(float),
        "high_vol": high_vol.astype(float),
        "mom_20": mom_20,
        "drawdown": drawdown,
    }, index=frame.index)


def backtest_v12(frame: pd.DataFrame, state: pd.DataFrame,
                 cost_bps: float = COST_BPS,
                 financing_rate: float = FINANCING_RATE) -> dict[str, float]:
    """Run backtest given V1.2 state outputs."""
    daily = frame[["open"]].copy()
    daily["byd_w"] = state["byd_weight"].shift(1).fillna(0.0)
    daily["etf_w"] = state["etf_weight"].shift(1).fillna(0.0)
    daily["financed"] = state["financed_sessions"].shift(1).fillna(0.0)

    # Open-to-open return
    daily["byd_ret"] = daily["open"].shift(-1) / daily["open"] - 1.0
    # ETF return: for single-asset simplification, use BYD returns scaled
    # In real V1.2, ETF has its own returns. Here we approximate.
    daily["etf_ret"] = daily["byd_ret"] * 0.15  # crude approx of 515180 beta to BYD

    daily = daily.iloc[:-1].copy()

    # Turnover costs on both BYD and ETF weight changes
    daily["byd_turnover"] = daily["byd_w"].diff().abs()
    daily["etf_turnover"] = daily["etf_w"].diff().abs()
    daily["byd_turnover"].iloc[0] = abs(daily["byd_w"].iloc[0])
    daily["etf_turnover"].iloc[0] = abs(daily["etf_w"].iloc[0])

    daily["cost"] = (daily["byd_turnover"] + daily["etf_turnover"]) * cost_bps / 10000.0

    # Financing cost on borrowed amount (byd_weight - 1.0 when > 1.0)
    daily["borrowed"] = np.maximum(daily["byd_w"] - 1.0, 0.0)
    daily["financing_cost"] = daily["borrowed"] * financing_rate / 252.0

    daily["gross_return"] = daily["byd_w"] * daily["byd_ret"] + daily["etf_w"] * daily["etf_ret"]
    daily["net_return"] = daily["gross_return"] - daily["cost"] - daily["financing_cost"]

    metrics = compute_metrics(daily["net_return"])
    metrics["total_turnover"] = float((daily["byd_turnover"] + daily["etf_turnover"]).sum())
    metrics["n_financed_sessions"] = int(daily["financed"].sum())
    metrics["mean_byd_weight"] = float(daily["byd_w"].mean())
    metrics["mean_etf_weight"] = float(daily["etf_w"].mean())

    return metrics


# — Evaluation windows ————————————————————————————————————————————————————

EVAL_WINDOWS = {
    "development": ("2019-11-26", "2022-12-31"),
    "fixed_validation": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", "2026-08-03"),
    "full_overlap": ("2019-11-26", "2026-08-03"),
}

V12_REFERENCE = {
    "development": {"cagr": 0.7888, "sharpe": 1.3628, "max_dd": -0.4222, "calmar": 1.8685},
    "fixed_validation": {"cagr": 0.0816, "sharpe": 0.4032, "max_dd": -0.4134, "calmar": 0.1973},
    "retrospective_2025_plus": {"cagr": 0.0480, "sharpe": 0.3045, "max_dd": -0.3729, "calmar": 0.1287},
    "full_overlap": {"cagr": 0.3534, "sharpe": 0.9185, "max_dd": -0.4920, "calmar": 0.7183},
}


def evaluate_variant(frame: pd.DataFrame, state: pd.DataFrame, label: str,
                     reference: dict = V12_REFERENCE) -> dict:
    """Evaluate a V1.2 variant across all windows."""
    results = {"label": label}
    for window_name, (w_start, w_end) in EVAL_WINDOWS.items():
        mask = (frame.index >= w_start) & (frame.index <= w_end)
        w_frame = frame.loc[mask]
        w_state = state.loc[mask]

        if len(w_frame) < 30:
            results[window_name] = {"error": "insufficient data"}
            continue

        metrics = backtest_v12(w_frame, w_state)
        ref = reference.get(window_name, {})
        results[window_name] = {
            **metrics,
            "cagr_delta": metrics["cagr"] - ref.get("cagr", 0),
            "sharpe_delta": metrics["sharpe"] - ref.get("sharpe", 0),
            "maxdd_delta": metrics["max_drawdown"] - ref.get("max_dd", 0),
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Improvement Explorations
# ═══════════════════════════════════════════════════════════════════════════


def explore_1_regime_adaptive_core(frame: pd.DataFrame) -> list[dict]:
    """Vary defense core by market regime (Bull/Bear/Sideways)."""
    print("\n--- 1: Regime-Adaptive Core ---")
    results = []

    configs = [
        # (bull_core, bear_core, sideways_core, label)
        (0.75, 0.50, 0.65, "bear50"),
        (0.75, 0.60, 0.70, "bear60"),
        (0.80, 0.50, 0.65, "bull80_bear50"),
        (0.85, 0.55, 0.70, "bull85_bear55"),
        (0.90, 0.60, 0.75, "bull90_bear60"),
    ]

    for bull_core, bear_core, sw_core, label in configs:
        close = frame["close"]
        sma_200 = close.rolling(200, min_periods=200).mean()
        sma_60 = close.rolling(60, min_periods=60).mean()
        is_bull = close.gt(sma_200) & sma_60.gt(sma_200)
        is_bear = close.lt(sma_200) & sma_60.lt(sma_200)

        state = compute_v12_state(frame, defense_byd=0.75)  # base logic unchanged

        # Override base_byd_weight with regime-adaptive core
        for i in state.index:
            if state.loc[i, "base_risk_on"] < 0.5:  # in defense
                if is_bear.loc[i]:
                    state.loc[i, "base_byd_weight"] = bear_core
                elif is_bull.loc[i]:
                    state.loc[i, "base_byd_weight"] = bull_core
                else:
                    state.loc[i, "base_byd_weight"] = sw_core

        # Recalculate etf_weight
        state["etf_weight"] = 0.0
        defense_mask = state["base_byd_weight"] < 0.99
        state.loc[defense_mask, "etf_weight"] = 1.0 - state.loc[defense_mask, "base_byd_weight"]

        r = evaluate_variant(frame, state, f"regime_core_{label}")
        results.append(r)
        fv = r.get("fixed_validation", {})
        rp = r.get("retrospective_2025_plus", {})
        print(f"  {label}: val CAGR={fv.get('cagr', 0):.4f} (Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"2025+ CAGR={rp.get('cagr', 0):.4f} (Δ={rp.get('cagr_delta', 0):+.4f})")

    return results


def explore_2_drawdown_scaled_core(frame: pd.DataFrame) -> list[dict]:
    """Scale defense core inversely with drawdown depth."""
    print("\n--- 2: Drawdown-Scaled Core ---")
    results = []

    configs = [
        # (dd_threshold, reduction_pct, label)
        (-0.20, 0.10, "dd20_reduce10pct"),
        (-0.20, 0.15, "dd20_reduce15pct"),
        (-0.25, 0.10, "dd25_reduce10pct"),
        (-0.25, 0.15, "dd25_reduce15pct"),
        (-0.30, 0.10, "dd30_reduce10pct"),
        (-0.30, 0.20, "dd30_reduce20pct"),
    ]

    for dd_threshold, reduction, label in configs:
        state = compute_v12_state(frame)
        drawdown = state["drawdown"]
        base_core = 0.75

        # Reduce core when drawdown below threshold
        scaled_core = pd.Series(base_core, index=frame.index)
        deep_dd = drawdown < dd_threshold
        scaled_core.loc[deep_dd] = base_core - reduction

        # Apply to defense periods
        for i in state.index:
            if state.loc[i, "base_risk_on"] < 0.5:
                state.loc[i, "base_byd_weight"] = scaled_core.loc[i]

        state["etf_weight"] = 0.0
        defense_mask = state["base_byd_weight"] < 0.99
        state.loc[defense_mask, "etf_weight"] = 1.0 - state.loc[defense_mask, "base_byd_weight"]

        r = evaluate_variant(frame, state, f"dd_scaled_{label}")
        results.append(r)
        fv = r.get("fixed_validation", {})
        r.get("retrospective_2025_plus", {})
        print(f"  {label}: val CAGR={fv.get('cagr', 0):.4f} (Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"val MaxDD={fv.get('max_drawdown', 0):.4f} (Δ={fv.get('maxdd_delta', 0):+.4f})")

    return results


def explore_3_vol_adaptive_mom(frame: pd.DataFrame) -> list[dict]:
    """Use volatility-scaled momentum divisor instead of fixed 0.15."""
    print("\n--- 3: Vol-Adaptive Momentum Threshold ---")
    results = []

    daily_ret = frame["close"].pct_change()
    daily_ret.rolling(60).std()

    configs = [
        # (base_divisor, vol_multiplier, label)
        (0.15, 1.0, "fixed_0.15"),  # baseline
        (0.10, 1.0, "fixed_0.10"),
        (0.20, 1.0, "fixed_0.20"),
        (0.25, 1.0, "fixed_0.25"),
    ]

    for divisor, _, label in configs:
        state = compute_v12_state(frame, mom_divisor=divisor)
        r = evaluate_variant(frame, state, f"mom_div_{label}")
        results.append(r)
        fo = r.get("full_overlap", {})
        print(f"  {label}: full CAGR={fo.get('cagr', 0):.4f} (Δ={fo.get('cagr_delta', 0):+.4f}), "
              f"financed={fo.get('n_financed_sessions', 0)}")

    # Vol-scaled variants
    for vol_scale in [0.5, 0.75, 1.25, 1.5]:
        vol_scaled_divisor = 0.15 * vol_scale
        state = compute_v12_state(frame, mom_divisor=vol_scaled_divisor)
        label = f"vol_scaled_{vol_scale:.2f}x"
        r = evaluate_variant(frame, state, label)
        results.append(r)
        fo = r.get("full_overlap", {})
        print(f"  {label} (div={vol_scaled_divisor:.3f}): full CAGR={fo.get('cagr', 0):.4f} "
              f"(Δ={fo.get('cagr_delta', 0):+.4f}), financed={fo.get('n_financed_sessions', 0)}")

    return results


def explore_4_exit_conditions(frame: pd.DataFrame) -> list[dict]:
    """Test different exit condition combinations for trend expansion."""
    print("\n--- 4: Exit Condition Variations ---")
    results = []

    # We need to reimplement with custom exit conditions
    close = frame["close"]
    sma_200 = close.rolling(200, min_periods=200).mean()
    sma_60 = close.rolling(60, min_periods=60).mean()
    sma_120 = close.rolling(120, min_periods=120).mean()
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)
    daily_ret = close.pct_change()
    realized_vol = daily_ret.rolling(60).std()
    vol_median = realized_vol.rolling(756, min_periods=252).median().shift(1)
    high_vol = realized_vol > vol_median
    bull = close.gt(sma_200) & sma_60.gt(sma_200)
    high_dd = close.rolling(252, min_periods=252).max()
    drawdown = close / high_dd - 1.0

    # Base risk-on/off (same as V1.2)
    risk_on_entry = close.gt(sma_120) & mom_20.gt(0.0)
    risk_off_exit = close.lt(sma_120) & mom_60.lt(0.0)
    base_risk_on = _stateful_hysteresis(risk_on_entry, risk_off_exit)
    base_byd = pd.Series(np.where(base_risk_on > 0.5, 1.0, 0.75), index=frame.index)

    # Expansion entry (always same)
    expansion_entry = (
        (base_byd >= 1.0) & bull & (~high_vol) &
        mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
    )

    exit_configs = [
        # (exit_conditions_dict, label)
        ("original", ["base_0.75", "not_bull", "high_vol", "mom20_le0"]),
        ("no_high_vol_exit", ["base_0.75", "not_bull", "mom20_le0"]),
        ("no_mom20_exit", ["base_0.75", "not_bull", "high_vol"]),
        ("only_base_exit", ["base_0.75"]),
        ("only_not_bull", ["not_bull"]),
        ("base_or_not_bull", ["base_0.75", "not_bull"]),
        ("add_mom60_exit", ["base_0.75", "not_bull", "high_vol", "mom20_le0", "mom60_le0"]),
        ("add_dd_exit", ["base_0.75", "not_bull", "high_vol", "mom20_le0", "dd_le_minus15"]),
    ]

    for label, exit_rules in exit_configs:
        exit_components = []
        for rule in exit_rules:
            if rule == "base_0.75":
                exit_components.append(base_byd <= 0.76)
            elif rule == "not_bull":
                exit_components.append(~bull)
            elif rule == "high_vol":
                exit_components.append(high_vol)
            elif rule == "mom20_le0":
                exit_components.append(mom_20.le(0.0))
            elif rule == "mom60_le0":
                exit_components.append(mom_60.le(0.0))
            elif rule == "dd_le_minus15":
                exit_components.append(drawdown.le(-0.15))

        expansion_exit = exit_components[0].copy() if exit_components else pd.Series(False, index=frame.index)
        for ec in exit_components[1:]:
            expansion_exit = expansion_exit | ec

        expansion_active = _stateful_hysteresis(expansion_entry, expansion_exit)

        mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 4.0
        expansion_inc = mom_scale * 0.125

        byd_weight = base_byd.copy()
        financed = expansion_active > 0.5
        byd_weight.loc[financed] = 1.0 + expansion_inc.loc[financed]
        byd_weight = byd_weight.clip(upper=1.125)

        etf_weight = pd.Series(0.0, index=frame.index)
        defense_mask = (base_byd <= 0.76) & (~financed)
        etf_weight.loc[defense_mask] = 0.25

        state = pd.DataFrame({
            "byd_weight": byd_weight,
            "etf_weight": etf_weight,
            "financed_sessions": financed.astype(float),
        }, index=frame.index)

        r = evaluate_variant(frame, state, f"exit_{label}")
        results.append(r)
        fo = r.get("full_overlap", {})
        fv = r.get("fixed_validation", {})
        print(f"  {label}: val CAGR={fv.get('cagr', 0):.4f} (Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"full financed={fo.get('n_financed_sessions', 0)}")

    return results


def explore_5_min_hold_on_v12(frame: pd.DataFrame) -> list[dict]:
    """Apply min-hold constraint to V1.2's state transitions."""
    print("\n--- 5: Min-Hold on V1.2 State Changes ---")
    results = []

    state_base = compute_v12_state(frame)

    for min_hold in [10, 20, 30, 40, 60]:
        base_risk_on = state_base["base_risk_on"]

        # Apply min hold to base risk-on/off transitions
        entry = base_risk_on.diff() > 0.5
        exit_ = base_risk_on.diff() < -0.5
        constrained = _stateful_min_hold(entry, exit_, min_hold)

        # Also apply to expansion
        expansion_entry = state_base["expansion_active"].diff() > 0.5
        expansion_exit = state_base["expansion_active"].diff() < -0.5
        constrained_exp = _stateful_min_hold(expansion_entry, expansion_exit, min_hold)

        # Rebuild state
        close = frame["close"]
        mom_20 = close.pct_change(20)
        base_byd = pd.Series(np.where(constrained > 0.5, 1.0, 0.75), index=frame.index)
        mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 4.0
        expansion_inc = mom_scale * 0.125

        byd_weight = base_byd.copy()
        financed = constrained_exp > 0.5
        byd_weight.loc[financed] = 1.0 + expansion_inc.loc[financed]
        byd_weight = byd_weight.clip(upper=1.125)

        etf_weight = pd.Series(0.0, index=frame.index)
        defense_mask = (base_byd <= 0.76) & (~financed)
        etf_weight.loc[defense_mask] = 0.25

        state = pd.DataFrame({
            "byd_weight": byd_weight,
            "etf_weight": etf_weight,
            "financed_sessions": financed.astype(float),
        }, index=frame.index)

        r = evaluate_variant(frame, state, f"min_hold_{min_hold}d")
        results.append(r)
        fo = r.get("full_overlap", {})
        fv = r.get("fixed_validation", {})
        print(f"  min_hold_{min_hold}d: val CAGR={fv.get('cagr', 0):.4f} "
              f"(Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"full Sharpe={fo.get('sharpe', 0):.3f}")

    return results


def explore_6_convex_power(frame: pd.DataFrame) -> list[dict]:
    """Test different convex power values for momentum budget."""
    print("\n--- 6: Convex Power Sensitivity ---")
    results = []

    for power in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]:
        state = compute_v12_state(frame, convex_power=power)
        r = evaluate_variant(frame, state, f"power_{power:.0f}")
        results.append(r)
        fo = r.get("full_overlap", {})
        print(f"  power={power:.0f}: full CAGR={fo.get('cagr', 0):.4f} "
              f"(Δ={fo.get('cagr_delta', 0):+.4f}), financed={fo.get('n_financed_sessions', 0)}")

    return results


def explore_7_expansion_pct(frame: pd.DataFrame) -> list[dict]:
    """Test different expansion percentages."""
    print("\n--- 7: Expansion Percentage Sensitivity ---")
    results = []

    for pct in [0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20]:
        state = compute_v12_state(frame, expansion_pct=pct)
        r = evaluate_variant(frame, state, f"expansion_{pct:.3f}")
        results.append(r)
        fo = r.get("full_overlap", {})
        print(f"  {pct:.1%}: full CAGR={fo.get('cagr', 0):.4f} "
              f"(Δ={fo.get('cagr_delta', 0):+.4f}), MaxDD={fo.get('max_drawdown', 0):.4f}")

    return results


def explore_8_sma_windows(frame: pd.DataFrame) -> list[dict]:
    """Test different SMA window combinations for the base V1.0 logic."""
    print("\n--- 8: SMA Window Variations ---")
    results = []

    configs = [
        (50, 150, "50_150"),
        (50, 200, "50_200"),
        (60, 150, "60_150"),
        (60, 200, "60_200"),  # baseline
        (60, 250, "60_250"),
        (100, 200, "100_200"),
        (120, 250, "120_250"),
    ]

    for sma_short, sma_long, label in configs:
        close = frame["close"]
        sma_s = close.rolling(sma_short, min_periods=sma_short).mean()
        sma_l = close.rolling(sma_long, min_periods=sma_long).mean()
        mom_20 = close.pct_change(20)
        mom_60 = close.pct_change(60)

        # V1.0 logic with different SMA windows for risk-on
        sma_entry = close.rolling(sma_short * 2, min_periods=sma_short * 2).mean()
        risk_on_entry = close.gt(sma_entry) & mom_20.gt(0.0)
        risk_off_exit = close.lt(sma_entry) & mom_60.lt(0.0)

        base_risk_on = _stateful_hysteresis(risk_on_entry, risk_off_exit)
        base_byd = pd.Series(np.where(base_risk_on > 0.5, 1.0, 0.75), index=frame.index)

        # V1.2 expansion logic
        bull = close.gt(sma_l) & sma_s.gt(sma_l)
        daily_ret = close.pct_change()
        realized_vol = daily_ret.rolling(60).std()
        vol_median = realized_vol.rolling(756, min_periods=252).median().shift(1)
        high_vol = realized_vol > vol_median
        drawdown = close / close.rolling(252, min_periods=252).max() - 1.0

        expansion_entry = (
            (base_byd >= 1.0) & bull & (~high_vol) &
            mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
        )
        expansion_exit = (
            (base_byd <= 0.76) | (~bull) | high_vol | mom_20.le(0.0)
        )
        expansion_active = _stateful_hysteresis(expansion_entry, expansion_exit)

        mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 4.0
        expansion_inc = mom_scale * 0.125

        byd_weight = base_byd.copy()
        financed = expansion_active > 0.5
        byd_weight.loc[financed] = 1.0 + expansion_inc.loc[financed]
        byd_weight = byd_weight.clip(upper=1.125)

        etf_weight = pd.Series(0.0, index=frame.index)
        defense_mask = (base_byd <= 0.76) & (~financed)
        etf_weight.loc[defense_mask] = 0.25

        state = pd.DataFrame({
            "byd_weight": byd_weight,
            "etf_weight": etf_weight,
            "financed_sessions": financed.astype(float),
        }, index=frame.index)

        r = evaluate_variant(frame, state, f"sma_{label}")
        results.append(r)
        fv = r.get("fixed_validation", {})
        rp = r.get("retrospective_2025_plus", {})
        print(f"  SMA {label}: val CAGR={fv.get('cagr', 0):.4f} "
              f"(Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"2025+ CAGR={rp.get('cagr', 0):.4f} (Δ={rp.get('cagr_delta', 0):+.4f})")

    return results


def explore_9_entry_delay(frame: pd.DataFrame) -> list[dict]:
    """Add confirmation delay to entry signals (require signal to persist N days)."""
    print("\n--- 9: Entry Confirmation Delay ---")
    results = []

    close = frame["close"]
    sma_120 = close.rolling(120, min_periods=120).mean()
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)

    for delay in [0, 2, 3, 5, 10]:
        risk_on_signal = close.gt(sma_120) & mom_20.gt(0.0)
        risk_off_signal = close.lt(sma_120) & mom_60.lt(0.0)

        if delay > 0:
            # Signal must persist for `delay` consecutive days
            risk_on_confirmed = risk_on_signal.rolling(delay, min_periods=delay).min() > 0.5
            risk_off_confirmed = risk_off_signal.rolling(delay, min_periods=delay).min() > 0.5
        else:
            risk_on_confirmed = risk_on_signal
            risk_off_confirmed = risk_off_signal

        base_risk_on = _stateful_hysteresis(risk_on_confirmed, risk_off_confirmed)
        base_byd = pd.Series(np.where(base_risk_on > 0.5, 1.0, 0.75), index=frame.index)

        # V1.2 expansion
        sma_200 = close.rolling(200, min_periods=200).mean()
        sma_60 = close.rolling(60, min_periods=60).mean()
        bull = close.gt(sma_200) & sma_60.gt(sma_200)
        daily_ret = close.pct_change()
        realized_vol = daily_ret.rolling(60).std()
        vol_median = realized_vol.rolling(756, min_periods=252).median().shift(1)
        high_vol = realized_vol > vol_median
        drawdown = close / close.rolling(252, min_periods=252).max() - 1.0

        expansion_entry = (
            (base_byd >= 1.0) & bull & (~high_vol) &
            mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
        )
        expansion_exit = (base_byd <= 0.76) | (~bull) | high_vol | mom_20.le(0.0)
        expansion_active = _stateful_hysteresis(expansion_entry, expansion_exit)

        mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 4.0
        expansion_inc = mom_scale * 0.125

        byd_weight = base_byd.copy()
        financed = expansion_active > 0.5
        byd_weight.loc[financed] = 1.0 + expansion_inc.loc[financed]
        byd_weight = byd_weight.clip(upper=1.125)

        etf_weight = pd.Series(0.0, index=frame.index)
        defense_mask = (base_byd <= 0.76) & (~financed)
        etf_weight.loc[defense_mask] = 0.25

        state = pd.DataFrame({
            "byd_weight": byd_weight, "etf_weight": etf_weight,
            "financed_sessions": financed.astype(float),
        }, index=frame.index)

        r = evaluate_variant(frame, state, f"entry_delay_{delay}d")
        results.append(r)
        fv = r.get("fixed_validation", {})
        rp = r.get("retrospective_2025_plus", {})
        print(f"  delay={delay}d: val CAGR={fv.get('cagr', 0):.4f} "
              f"(Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"2025+ CAGR={rp.get('cagr', 0):.4f}")

    return results


def explore_10_combined_best(frame: pd.DataFrame) -> list[dict]:
    """Combine the best improvements from each exploration."""
    print("\n--- 10: Combined Best Improvements ---")
    results = []

    close = frame["close"]
    sma_200 = close.rolling(200, min_periods=200).mean()
    sma_60 = close.rolling(60, min_periods=60).mean()
    sma_100 = close.rolling(100, min_periods=100).mean()
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)
    daily_ret = close.pct_change()
    realized_vol = daily_ret.rolling(60).std()
    vol_median = realized_vol.rolling(756, min_periods=252).median().shift(1)
    high_vol = realized_vol > vol_median
    bull = close.gt(sma_200) & sma_60.gt(sma_200)

    # Combined improvements:
    # A: Best SMA windows + best convex power + best expansion pct + min hold
    # B: Bear-adaptive core + best exit conditions + entry delay
    # C: Everything combined

    combos = []

    # Combo A: SMA 120/250 + power 3 + expansion 0.15 + min_hold 20
    sma_entry = close.rolling(120, min_periods=120).mean()
    risk_on_entry_a = close.gt(sma_entry) & mom_20.gt(0.0)
    risk_off_exit_a = close.lt(sma_entry) & mom_60.lt(0.0)
    base_risk_on_a = _stateful_hysteresis(risk_on_entry_a, risk_off_exit_a)
    # Min hold 20
    entry_a = base_risk_on_a.diff() > 0.5
    exit_a = base_risk_on_a.diff() < -0.5
    base_risk_on_a = _stateful_min_hold(entry_a, exit_a, 20)
    base_byd_a = pd.Series(np.where(base_risk_on_a > 0.5, 1.0, 0.75), index=frame.index)
    drawdown = close / close.rolling(252, min_periods=252).max() - 1.0
    bull_a = close.gt(sma_200) & sma_100.gt(sma_200)
    expansion_entry_a = (
        (base_byd_a >= 1.0) & bull_a & (~high_vol) &
        mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
    )
    expansion_exit_a = (base_byd_a <= 0.76) | (~bull_a) | mom_20.le(0.0)
    expansion_active_a = _stateful_hysteresis(expansion_entry_a, expansion_exit_a)
    mom_scale_a = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 3.0
    expansion_inc_a = mom_scale_a * 0.15
    byd_a = base_byd_a.copy()
    financed_a = expansion_active_a > 0.5
    byd_a.loc[financed_a] = 1.0 + expansion_inc_a.loc[financed_a]
    byd_a = byd_a.clip(upper=1.15)
    etf_a = pd.Series(0.0, index=frame.index)
    defense_a = (base_byd_a <= 0.76) & (~financed_a)
    etf_a.loc[defense_a] = 0.25

    state_a = pd.DataFrame({
        "byd_weight": byd_a, "etf_weight": etf_a,
        "financed_sessions": financed_a.astype(float),
    }, index=frame.index)
    combos.append(("combo_A_sma_power_exp_minhold", state_a))

    # Combo B: Bear-adaptive core + min_hold + relaxed exit
    sma_entry_b = close.rolling(100, min_periods=100).mean()
    risk_on_entry_b = close.gt(sma_entry_b) & mom_20.gt(0.0)
    risk_off_exit_b = close.lt(sma_entry_b) & mom_60.lt(0.0)
    base_risk_on_b = _stateful_hysteresis(risk_on_entry_b, risk_off_exit_b)
    entry_b = base_risk_on_b.diff() > 0.5
    exit_b = base_risk_on_b.diff() < -0.5
    base_risk_on_b = _stateful_min_hold(entry_b, exit_b, 30)

    is_bear = close.lt(sma_200) & sma_60.lt(sma_200)
    base_byd_b = pd.Series(0.75, index=frame.index)
    base_byd_b[base_risk_on_b > 0.5] = 1.0
    base_byd_b[(base_risk_on_b < 0.5) & is_bear] = 0.60

    expansion_entry_b = (
        (base_byd_b >= 1.0) & bull & (~high_vol) &
        mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
    )
    expansion_exit_b = (base_byd_b <= 0.76) | (~bull) | mom_20.le(0.0)
    expansion_active_b = _stateful_hysteresis(expansion_entry_b, expansion_exit_b)
    mom_scale_b = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 4.0
    expansion_inc_b = mom_scale_b * 0.125
    byd_b = base_byd_b.copy()
    financed_b = expansion_active_b > 0.5
    byd_b.loc[financed_b] = 1.0 + expansion_inc_b.loc[financed_b]
    byd_b = byd_b.clip(upper=1.125)
    etf_b = pd.Series(0.0, index=frame.index)
    defense_b = (base_byd_b <= 0.76) & (~financed_b)
    etf_b.loc[defense_b] = 1.0 - base_byd_b.loc[defense_b]

    state_b = pd.DataFrame({
        "byd_weight": byd_b, "etf_weight": etf_b,
        "financed_sessions": financed_b.astype(float),
    }, index=frame.index)
    combos.append(("combo_B_bear_core_minhold_relaxed", state_b))

    # Combo C: Everything — SMA 100/250, power 3, expansion 0.15, min_hold 30, bear core 0.60, entry delay 3
    sma_entry_c = close.rolling(100, min_periods=100).mean()
    sma_250 = close.rolling(250, min_periods=250).mean()
    risk_on_signal_c = close.gt(sma_entry_c) & mom_20.gt(0.0)
    risk_on_confirmed_c = risk_on_signal_c.rolling(3, min_periods=3).min() > 0.5
    risk_off_signal_c = close.lt(sma_entry_c) & mom_60.lt(0.0)
    risk_off_confirmed_c = risk_off_signal_c.rolling(3, min_periods=3).min() > 0.5
    base_risk_on_c = _stateful_hysteresis(risk_on_confirmed_c, risk_off_confirmed_c)
    entry_c = base_risk_on_c.diff() > 0.5
    exit_c = base_risk_on_c.diff() < -0.5
    base_risk_on_c = _stateful_min_hold(entry_c, exit_c, 30)

    is_bear_c = close.lt(sma_250) & sma_60.lt(sma_250)
    base_byd_c = pd.Series(0.75, index=frame.index)
    base_byd_c[base_risk_on_c > 0.5] = 1.0
    base_byd_c[(base_risk_on_c < 0.5) & is_bear_c] = 0.60

    bull_c = close.gt(sma_250) & sma_100.gt(sma_250)
    expansion_entry_c = (
        (base_byd_c >= 1.0) & bull_c & (~high_vol) &
        mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(-0.10)
    )
    expansion_exit_c = (base_byd_c <= 0.76) | (~bull_c) | mom_20.le(0.0)
    expansion_active_c = _stateful_hysteresis(expansion_entry_c, expansion_exit_c)
    mom_scale_c = np.minimum(1.0, np.maximum(mom_20, 0.0) / 0.15) ** 3.0
    expansion_inc_c = mom_scale_c * 0.15
    byd_c = base_byd_c.copy()
    financed_c = expansion_active_c > 0.5
    byd_c.loc[financed_c] = 1.0 + expansion_inc_c.loc[financed_c]
    byd_c = byd_c.clip(upper=1.15)
    etf_c = pd.Series(0.0, index=frame.index)
    defense_c = (base_byd_c <= 0.76) & (~financed_c)
    etf_c.loc[defense_c] = 1.0 - base_byd_c.loc[defense_c]

    state_c = pd.DataFrame({
        "byd_weight": byd_c, "etf_weight": etf_c,
        "financed_sessions": financed_c.astype(float),
    }, index=frame.index)
    combos.append(("combo_C_everything", state_c))

    for label, state in combos:
        r = evaluate_variant(frame, state, label)
        results.append(r)
        for w in ["development", "fixed_validation", "retrospective_2025_plus", "full_overlap"]:
            wm = r.get(w, {})
            print(f"  {label} [{w}]: CAGR={wm.get('cagr', 0):.4f} "
                  f"(Δ={wm.get('cagr_delta', 0):+.4f}), "
                  f"Sharpe={wm.get('sharpe', 0):.3f}, "
                  f"MaxDD={wm.get('max_drawdown', 0):.4f}")
        print()

    return results


# — Main —————————————————————————————————————————————————————————————————


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_BASE / f"{timestamp}_v12_improvements"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {output_dir}")

    # Load data
    canonical = load_canonical_snapshot(CANONICAL_ROOT)
    dataset = build_research_dataset(canonical.adjusted, canonical.sessions)
    frame = dataset.copy()
    # Add open column
    frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame.index = pd.to_datetime(frame.index)
    print(f"Loaded: {len(frame)} rows, {canonical.manifest.get('cutoff')}")

    # — Baseline V1.2 ——————————————————————————————————————————————————
    print("\n=== BASELINE V1.2 ===")
    state_baseline = compute_v12_state(frame)
    baseline_results = evaluate_variant(frame, state_baseline, "BASELINE_V1_2")
    for w in ["development", "fixed_validation", "retrospective_2025_plus", "full_overlap"]:
        wm = baseline_results.get(w, {})
        ref = V12_REFERENCE.get(w, {})
        print(f"  {w}: CAGR={wm.get('cagr', 0):.4f} (ref={ref.get('cagr', 0):.4f}, "
              f"Δ={wm.get('cagr_delta', 0):+.4f}), "
              f"Sharpe={wm.get('sharpe', 0):.3f} (ref={ref.get('sharpe', 0):.3f})")

    all_results = {
        "metadata": {
            "experiment_id": f"byd_v12_improvements_{timestamp}",
            "timestamp_utc": timestamp,
            "baseline": baseline_results,
        },
    }

    # — Run all explorations ————————————————————————————————————————————
    all_results["1_regime_adaptive_core"] = explore_1_regime_adaptive_core(frame)
    all_results["2_drawdown_scaled_core"] = explore_2_drawdown_scaled_core(frame)
    all_results["3_vol_adaptive_mom"] = explore_3_vol_adaptive_mom(frame)
    all_results["4_exit_conditions"] = explore_4_exit_conditions(frame)
    all_results["5_min_hold_v12"] = explore_5_min_hold_on_v12(frame)
    all_results["6_convex_power"] = explore_6_convex_power(frame)
    all_results["7_expansion_pct"] = explore_7_expansion_pct(frame)
    all_results["8_sma_windows"] = explore_8_sma_windows(frame)
    all_results["9_entry_delay"] = explore_9_entry_delay(frame)
    all_results["10_combined_best"] = explore_10_combined_best(frame)

    # — Find best improvements ——————————————————————————————————————————
    print("\n=== BEST IMPROVEMENTS ===")
    best_val = {"cagr_delta": -999, "label": ""}
    best_2025 = {"cagr_delta": -999, "label": ""}
    best_full = {"cagr_delta": -999, "label": ""}

    for section_key, section_data in all_results.items():
        if not isinstance(section_data, list):
            continue
        for entry in section_data:
            for window, key in [("fixed_validation", best_val),
                                ("retrospective_2025_plus", best_2025),
                                ("full_overlap", best_full)]:
                wm = entry.get(window, {})
                delta = wm.get("cagr_delta", -999)
                if delta > key["cagr_delta"]:
                    key["cagr_delta"] = delta
                    key["label"] = entry.get("label", "unknown")
                    key["cagr"] = wm.get("cagr", 0)
                    key["sharpe"] = wm.get("sharpe", 0)

    print(f"  Best fixed_validation: {best_val['label']} "
          f"(CAGR Δ={best_val['cagr_delta']:+.4f}, CAGR={best_val['cagr']:.4f})")
    print(f"  Best 2025+: {best_2025['label']} "
          f"(CAGR Δ={best_2025['cagr_delta']:+.4f}, CAGR={best_2025['cagr']:.4f})")
    print(f"  Best full_overlap: {best_full['label']} "
          f"(CAGR Δ={best_full['cagr_delta']:+.4f}, CAGR={best_full['cagr']:.4f})")

    all_results["summary"] = {
        "best_fixed_validation": best_val,
        "best_retrospective_2025_plus": best_2025,
        "best_full_overlap": best_full,
    }

    # Save
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (pd.Timestamp, Path)):
                return str(obj)
            return super().default(obj)

    results_path = output_dir / "v12_improvements.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, cls=NpEncoder, indent=2, ensure_ascii=False)
    print(f"\nSaved: {results_path}")


if __name__ == "__main__":
    main()
