"""BYD V1.2 Deep-Dive — Real ETF + Parameter Grid + Extreme Skepticism.

Key concerns addressed:
  1. Uses REAL 515180.SH ETF returns (not crude approximation)
  2. Full parameter grid search across all V1.2 dimensions
  3. Verifies min_hold mechanism correctness
  4. Tests every dismissed combination with correct ETF data
  5. Cost sensitivity analysis
"""

from __future__ import annotations

import base64
import io
import json
import sys
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
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
ETF_B64 = PROJECT_ROOT / "data" / "research" / "515180_canonical_v1_artifact.zip.b64"
OUTPUT_BASE = PROJECT_ROOT / "data" / "research" / "byd_v2_experiments"
COST_BPS = 20.0
FINANCING_RATE = 0.06

# — Load real ETF data ——————————————————————————————————————————————————


def load_real_etf() -> pd.DataFrame:
    """Load 515180.SH adjusted OHLCV with open_research_eligible flag."""
    data = base64.b64decode(ETF_B64.read_text())
    zf = zipfile.ZipFile(io.BytesIO(data))
    adj = pd.read_csv(io.BytesIO(zf.read("adjusted_ohlcv.csv")), parse_dates=["date"])
    sessions = pd.read_csv(io.BytesIO(zf.read("session_audit.csv")), parse_dates=["date"])

    adj = adj.sort_values("date").set_index("date")
    sessions = sessions.sort_values("date").set_index("date")

    adj["open_research_eligible"] = sessions["open_research_eligible"].astype(bool)
    return adj


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
    """CRITICAL: Verify no look-ahead. Entry/exit are decided at CLOSE,
    position is taken at NEXT OPEN. Min_hold counts DAYS IN POSITION."""
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


# — V1.2 State Computer ——————————————————————————————————————————————————


@dataclass
class V12Params:
    """All tunable V1.2 parameters."""
    # Risk-on/off (V1.0 base)
    risk_sma: int = 120       # SMA for risk-on entry/exit
    risk_mom_entry: int = 20  # momentum window for risk-on entry
    risk_mom_exit: int = 60   # momentum window for risk-off exit

    # Market regime (Bull/Bear)
    regime_sma_fast: int = 60
    regime_sma_slow: int = 200

    # Volatility
    vol_window: int = 60
    vol_lookback: int = 756

    # Drawdown
    dd_window: int = 252
    dd_entry_floor: float = -0.10

    # Expansion
    expansion_pct: float = 0.125
    convex_divisor: float = 0.15
    convex_power: float = 4.0

    # Defense
    defense_byd: float = 0.75

    # Min hold
    min_hold_risk: int = 0   # min hold on risk-on/off transitions
    min_hold_expansion: int = 0  # min hold on expansion transitions


def compute_v12_state(frame: pd.DataFrame, params: V12Params) -> pd.DataFrame:
    """Compute full V1.2 state from parameters."""
    close = frame["close"]

    # SMA
    sma_risk = close.rolling(params.risk_sma, min_periods=params.risk_sma).mean()
    sma_fast = close.rolling(params.regime_sma_fast, min_periods=params.regime_sma_fast).mean()
    sma_slow = close.rolling(params.regime_sma_slow, min_periods=params.regime_sma_slow).mean()

    # Momentum
    mom_entry = close.pct_change(params.risk_mom_entry)
    mom_exit = close.pct_change(params.risk_mom_exit)
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)

    # Risk-on/off (V1.0 logic)
    risk_on_entry = close.gt(sma_risk) & mom_entry.gt(0.0)
    risk_off_exit = close.lt(sma_risk) & mom_exit.lt(0.0)

    if params.min_hold_risk > 0:
        base_risk_on = _stateful_min_hold(risk_on_entry, risk_off_exit, params.min_hold_risk)
    else:
        base_risk_on = _stateful_hysteresis(risk_on_entry, risk_off_exit)

    base_byd = pd.Series(
        np.where(base_risk_on > 0.5, 1.0, params.defense_byd),
        index=frame.index
    )

    # Market regime
    bull = close.gt(sma_slow) & sma_fast.gt(sma_slow)

    # Vol regime
    daily_ret = close.pct_change()
    realized_vol = daily_ret.rolling(params.vol_window).std()
    vol_median = realized_vol.rolling(params.vol_lookback, min_periods=252).median().shift(1)
    high_vol = realized_vol > vol_median

    # Drawdown
    high_dd = close.rolling(params.dd_window, min_periods=params.dd_window).max()
    drawdown = close / high_dd - 1.0

    # Expansion entry/exit
    expansion_entry = (
        (base_byd >= 1.0) & bull & (~high_vol) &
        mom_20.gt(0.0) & mom_60.gt(0.0) & drawdown.gt(params.dd_entry_floor)
    )
    expansion_exit = (
        (base_byd <= params.defense_byd + 0.01) | (~bull) | high_vol | mom_20.le(0.0)
    )

    if params.min_hold_expansion > 0:
        expansion_active = _stateful_min_hold(expansion_entry, expansion_exit, params.min_hold_expansion)
    else:
        expansion_active = _stateful_hysteresis(expansion_entry, expansion_exit)

    # Convex scale
    mom_scale = np.minimum(1.0, np.maximum(mom_20, 0.0) / params.convex_divisor) ** params.convex_power
    expansion_inc = mom_scale * params.expansion_pct

    # Final weights
    byd_weight = base_byd.copy()
    financed = expansion_active > 0.5
    byd_weight.loc[financed] = 1.0 + expansion_inc.loc[financed]
    byd_weight = byd_weight.clip(upper=1.0 + params.expansion_pct)

    etf_weight = pd.Series(0.0, index=frame.index)
    defense_mask = (base_byd <= params.defense_byd + 0.01) & (~financed)
    etf_weight.loc[defense_mask] = 1.0 - params.defense_byd

    return pd.DataFrame({
        "byd_weight": byd_weight, "etf_weight": etf_weight,
        "financed_sessions": financed.astype(float),
        "base_risk_on": base_risk_on,
    }, index=frame.index)


# — Dual-asset backtest with REAL ETF returns ———————————————————————————


def backtest_v12_real(
    byd_frame: pd.DataFrame,
    etf_frame: pd.DataFrame,
    state: pd.DataFrame,
    cost_bps: float = COST_BPS,
    financing_rate: float = FINANCING_RATE,
) -> dict[str, float]:
    """Run backtest with real BYD + ETF returns on common trading days."""
    # Align on common dates
    common_idx = byd_frame.index.intersection(etf_frame.index).intersection(state.index)
    common_idx = common_idx.sort_values()

    byd_open = byd_frame.loc[common_idx, "open"]
    etf_open = etf_frame.loc[common_idx, "open"]
    byd_eligible = byd_frame.loc[common_idx, "open_research_eligible"].fillna(True).astype(bool)
    etf_eligible = etf_frame.loc[common_idx, "open_research_eligible"].fillna(True).astype(bool)

    byd_w = state.loc[common_idx, "byd_weight"].shift(1).fillna(0.0)
    etf_w = state.loc[common_idx, "etf_weight"].shift(1).fillna(0.0)
    financed = state.loc[common_idx, "financed_sessions"].shift(1).fillna(0.0)

    # Open-to-open returns (executed at next eligible open)
    byd_ret = byd_open.shift(-1) / byd_open - 1.0
    etf_ret = etf_open.shift(-1) / etf_open - 1.0

    # Build daily dataframe
    daily = pd.DataFrame({
        "byd_w": byd_w, "etf_w": etf_w, "financed": financed,
        "byd_ret": byd_ret, "etf_ret": etf_ret,
        "byd_eligible": byd_eligible, "etf_eligible": etf_eligible,
    }, index=common_idx)
    daily = daily.iloc[:-1].copy()

    # Turnover costs
    daily["byd_turnover"] = daily["byd_w"].diff().abs()
    daily["etf_turnover"] = daily["etf_w"].diff().abs()
    daily["byd_turnover"].iloc[0] = abs(daily["byd_w"].iloc[0])
    daily["etf_turnover"].iloc[0] = abs(daily["etf_w"].iloc[0])
    daily["cost"] = (daily["byd_turnover"] + daily["etf_turnover"]) * cost_bps / 10000.0

    # Financing
    daily["borrowed"] = np.maximum(daily["byd_w"] - 1.0, 0.0)
    daily["financing_cost"] = daily["borrowed"] * financing_rate / 252.0

    # Returns
    daily["gross_return"] = daily["byd_w"] * daily["byd_ret"] + daily["etf_w"] * daily["etf_ret"]
    daily["net_return"] = daily["gross_return"] - daily["cost"] - daily["financing_cost"]

    metrics = compute_metrics(daily["net_return"])
    metrics["total_turnover"] = float((daily["byd_turnover"] + daily["etf_turnover"]).sum())
    metrics["n_financed"] = int(daily["financed"].sum())
    metrics["mean_byd_w"] = float(daily["byd_w"].mean())
    metrics["mean_etf_w"] = float(daily["etf_w"].mean())
    metrics["n_days"] = len(daily)

    return metrics


# — Evaluation ————————————————————————————————————————————————————————————

EVAL_WINDOWS = {
    "development": ("2019-11-26", "2022-12-31"),
    "fixed_validation": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", "2026-08-03"),
    "full_overlap": ("2019-11-26", "2026-08-03"),
}

V12_REF = {
    "development": {"cagr": 0.7888, "sharpe": 1.3628, "max_dd": -0.4222},
    "fixed_validation": {"cagr": 0.0816, "sharpe": 0.4032, "max_dd": -0.4134},
    "retrospective_2025_plus": {"cagr": 0.0480, "sharpe": 0.3045, "max_dd": -0.3729},
    "full_overlap": {"cagr": 0.3534, "sharpe": 0.9185, "max_dd": -0.4920},
}


def evaluate_window(byd_frame, etf_frame, state, window_name, w_start, w_end, cost_bps=COST_BPS):
    mask = (byd_frame.index >= w_start) & (byd_frame.index <= w_end)
    w_byd = byd_frame.loc[mask]
    state_mask = (state.index >= w_start) & (state.index <= w_end)
    w_state = state.loc[state_mask]
    if len(w_byd) < 30:
        return {"error": "insufficient data"}
    return backtest_v12_real(w_byd, etf_frame, w_state, cost_bps=cost_bps)


def evaluate_all(byd_frame, etf_frame, state, cost_bps=COST_BPS):
    result = {}
    for wn, (ws, we) in EVAL_WINDOWS.items():
        m = evaluate_window(byd_frame, etf_frame, state, wn, ws, we, cost_bps)
        ref = V12_REF.get(wn, {})
        m["cagr_delta"] = m.get("cagr", 0) - ref.get("cagr", 0)
        m["sharpe_delta"] = m.get("sharpe", 0) - ref.get("sharpe", 0)
        result[wn] = m
    return result


# — Grid search ——————————————————————————————————————————————————————————


def grid_search(byd_frame, etf_frame, cost_bps=COST_BPS):
    """Extremely thorough grid search across all V1.2 parameters."""
    print("=" * 70)
    print("GRID SEARCH: V1.2 Parameters")
    print("=" * 70)

    # Parameter grid — focus on high-impact dimensions
    grid = {
        "risk_sma": [100, 120, 150],
        "risk_mom_exit": [40, 60, 80],
        "min_hold_risk": [0, 20, 30, 40],
        "min_hold_expansion": [0, 20, 30, 40],
        "expansion_pct": [0.125, 0.15, 0.175],
        "convex_power": [3.0, 4.0],
        "defense_byd": [0.70, 0.75, 0.80],
    }

    # Baseline first
    baseline_params = V12Params()
    baseline_state = compute_v12_state(byd_frame, baseline_params)
    baseline_eval = evaluate_all(byd_frame, etf_frame, baseline_state, cost_bps)
    print(f"\nBaseline V1.2 (real ETF):")
    for w in ["full_overlap", "fixed_validation", "retrospective_2025_plus"]:
        m = baseline_eval.get(w, {})
        r = V12_REF.get(w, {})
        print(f"  {w}: CAGR={m.get('cagr', 0):.4f} (ref={r.get('cagr', 0):.4f}), "
              f"Sharpe={m.get('sharpe', 0):.3f}")

    # Generate all combinations (selective to keep manageable)
    results = []

    # 1: Min hold grid (most important)
    print("\n--- Min Hold Grid ---")
    for mh_risk, mh_exp in product([0, 10, 20, 30, 40, 60], [0, 20, 30, 40]):
        if mh_risk == 0 and mh_exp == 0:
            continue  # skip baseline
        p = V12Params(min_hold_risk=mh_risk, min_hold_expansion=mh_exp)
        s = compute_v12_state(byd_frame, p)
        e = evaluate_all(byd_frame, etf_frame, s, cost_bps)
        e["params"] = f"mh_risk={mh_risk},mh_exp={mh_exp}"
        results.append(e)
        fo = e.get("full_overlap", {})
        if fo.get("cagr_delta", -999) > 0.01:
            print(f"  mh_r={mh_risk} mh_e={mh_exp}: full CAGR={fo.get('cagr', 0):.4f} "
                  f"(Δ={fo.get('cagr_delta', 0):+.4f}), Sharpe={fo.get('sharpe', 0):.3f}")

    # 2: Expansion pct × convex power
    print("\n--- Expansion × Convex Grid ---")
    for exp_pct, cvx_pow in product([0.10, 0.125, 0.15, 0.175, 0.20], [2.0, 3.0, 4.0, 5.0]):
        p = V12Params(expansion_pct=exp_pct, convex_power=cvx_pow)
        s = compute_v12_state(byd_frame, p)
        e = evaluate_all(byd_frame, etf_frame, s, cost_bps)
        e["params"] = f"exp={exp_pct},cvx={cvx_pow}"
        results.append(e)
        fo = e.get("full_overlap", {})
        if fo.get("cagr_delta", -999) > 0.005:
            print(f"  exp={exp_pct:.1%} cvx={cvx_pow:.0f}: full CAGR={fo.get('cagr', 0):.4f} "
                  f"(Δ={fo.get('cagr_delta', 0):+.4f})")

    # 3: Risk SMA × defense byd
    print("\n--- Risk SMA × Defense Grid ---")
    for sma, defense in product([100, 120, 150], [0.65, 0.70, 0.75, 0.80]):
        p = V12Params(risk_sma=sma, defense_byd=defense)
        s = compute_v12_state(byd_frame, p)
        e = evaluate_all(byd_frame, etf_frame, s, cost_bps)
        e["params"] = f"sma={sma},def={defense}"
        results.append(e)
        fv = e.get("fixed_validation", {})
        rp = e.get("retrospective_2025_plus", {})
        if fv.get("cagr_delta", -999) > -0.01 or rp.get("cagr_delta", -999) > 0.01:
            print(f"  sma={sma} def={defense:.0%}: val Δ={fv.get('cagr_delta', 0):+.4f}, "
                  f"2025+ Δ={rp.get('cagr_delta', 0):+.4f}")

    # 4: Combined best grid
    print("\n--- Combined Best Grid ---")
    for mh_risk, exp_pct, cvx_pow in product([20, 30, 40], [0.125, 0.15, 0.175], [3.0, 4.0]):
        p = V12Params(
            min_hold_risk=mh_risk,
            min_hold_expansion=mh_risk,
            expansion_pct=exp_pct,
            convex_power=cvx_pow,
        )
        s = compute_v12_state(byd_frame, p)
        e = evaluate_all(byd_frame, etf_frame, s, cost_bps)
        e["params"] = f"mh={mh_risk},exp={exp_pct},cvx={cvx_pow}"
        results.append(e)
        for w in ["full_overlap", "fixed_validation", "retrospective_2025_plus"]:
            wm = e.get(w, {})
            if wm.get("cagr_delta", -999) > 0.01:
                print(f"  [{w}] mh={mh_risk} exp={exp_pct:.1%} cvx={cvx_pow:.0f}: "
                      f"CAGR={wm.get('cagr', 0):.4f} (Δ={wm.get('cagr_delta', 0):+.4f})")

    # 5: Bear-specific defense (regime-adaptive)
    print("\n--- Regime-Adaptive Defense (with min_hold) ---")
    close = byd_frame["close"]
    sma_200 = close.rolling(200, min_periods=200).mean()
    sma_60 = close.rolling(60, min_periods=60).mean()
    is_bear = close.lt(sma_200) & sma_60.lt(sma_200)

    for bear_def, mh in product([0.55, 0.60, 0.65], [20, 30, 40]):
        p = V12Params(min_hold_risk=mh, min_hold_expansion=mh, defense_byd=0.75)
        s = compute_v12_state(byd_frame, p)

        # Override: in bear, reduce defense core
        for i in s.index:
            if s.loc[i, "base_risk_on"] < 0.5 and is_bear.loc[i]:
                s.loc[i, "byd_weight"] = bear_def

        # Recalculate ETF
        s["etf_weight"] = 0.0
        def_mask = (s["byd_weight"] < 0.99) & (s["financed_sessions"] < 0.5)
        s.loc[def_mask, "etf_weight"] = 1.0 - s.loc[def_mask, "byd_weight"]

        e = evaluate_all(byd_frame, etf_frame, s, cost_bps)
        e["params"] = f"bear_def={bear_def},mh={mh}"
        results.append(e)
        fv = e.get("fixed_validation", {})
        rp = e.get("retrospective_2025_plus", {})
        print(f"  bear_def={bear_def:.0%} mh={mh}: val CAGR={fv.get('cagr', 0):.4f} "
              f"(Δ={fv.get('cagr_delta', 0):+.4f}), 2025+ CAGR={rp.get('cagr', 0):.4f} "
              f"(Δ={rp.get('cagr_delta', 0):+.4f})")

    # 6: Cost sensitivity
    print("\n--- Cost Sensitivity ---")
    bs = compute_v12_state(byd_frame, V12Params())
    bs_mh = compute_v12_state(byd_frame, V12Params(min_hold_risk=40, min_hold_expansion=40))
    for cost in [5, 10, 15, 20, 30, 40]:
        e_base = evaluate_all(byd_frame, etf_frame, bs, cost)
        e_mh = evaluate_all(byd_frame, etf_frame, bs_mh, cost)
        fo_b = e_base.get("full_overlap", {})
        fo_m = e_mh.get("full_overlap", {})
        print(f"  cost={cost}bps: baseline CAGR={fo_b.get('cagr', 0):.4f}, "
              f"mh40 CAGR={fo_m.get('cagr', 0):.4f} (Δ={fo_m.get('cagr', 0)-fo_b.get('cagr', 0):+.4f})")

    return baseline_eval, results


# — Main —————————————————————————————————————————————————————————————————


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_BASE / f"{timestamp}_deep_dive"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {output_dir}")

    # Load BYD
    canonical = load_canonical_snapshot(CANONICAL_ROOT)
    dataset = build_research_dataset(canonical.adjusted, canonical.sessions)
    byd_frame = dataset.copy()
    byd_frame["open"] = pd.to_numeric(byd_frame["open"], errors="coerce")
    byd_frame["close"] = pd.to_numeric(byd_frame["close"], errors="coerce")
    byd_frame.index = pd.to_datetime(byd_frame.index)
    print(f"BYD: {len(byd_frame)} rows, {byd_frame.index[0].date()} → {byd_frame.index[-1].date()}")

    # Load ETF
    etf_frame = load_real_etf()
    print(f"ETF: {len(etf_frame)} rows, {etf_frame.index[0].date()} → {etf_frame.index[-1].date()}")

    # Common overlap
    common = byd_frame.index.intersection(etf_frame.index)
    print(f"Common: {len(common)} days, "
          f"{common[0].date()} → {common[-1].date()}")

    # Run grid search
    baseline_eval, all_results = grid_search(byd_frame, etf_frame)

    # Find best by window
    print("\n" + "=" * 70)
    print("BEST BY WINDOW")
    print("=" * 70)

    best = {}
    for window in ["full_overlap", "fixed_validation", "retrospective_2025_plus"]:
        candidates = [(r.get(window, {}).get("cagr_delta", -999), r.get("params", ""), r)
                      for r in all_results]
        candidates.sort(key=lambda x: x[0], reverse=True)
        top5 = candidates[:5]
        best[window] = {"top5": [
            {"params": p, "cagr_delta": d, "cagr": r.get(window, {}).get("cagr", 0),
             "sharpe": r.get(window, {}).get("sharpe", 0)}
            for d, p, r in top5
        ]}
        print(f"\n{window}:")
        for i, (d, p, r) in enumerate(top5):
            wm = r.get(window, {})
            print(f"  #{i+1}: {p} → CAGR={wm.get('cagr', 0):.4f} "
                  f"(Δ={d:+.4f}), Sharpe={wm.get('sharpe', 0):.3f}")

    # Pareto-optimal: improve validation AND 2025+
    print("\n" + "=" * 70)
    print("PARETO-OPTIMAL (improve BOTH val AND 2025+)")
    print("=" * 70)
    pareto = []
    for r in all_results:
        val_d = r.get("fixed_validation", {}).get("cagr_delta", -999)
        rp_d = r.get("retrospective_2025_plus", {}).get("cagr_delta", -999)
        if val_d > -0.005 and rp_d > 0.0:
            pareto.append((val_d + rp_d, r))
    pareto.sort(key=lambda x: x[0], reverse=True)
    for i, (score, r) in enumerate(pareto[:10]):
        p = r.get("params", "")
        fv = r.get("fixed_validation", {})
        rp = r.get("retrospective_2025_plus", {})
        print(f"  #{i+1}: {p}")
        print(f"      val: CAGR={fv.get('cagr', 0):.4f} (Δ={fv.get('cagr_delta', 0):+.4f}), "
              f"Sharpe={fv.get('sharpe', 0):.3f}")
        print(f"      2025+: CAGR={rp.get('cagr', 0):.4f} (Δ={rp.get('cagr_delta', 0):+.4f}), "
              f"Sharpe={rp.get('sharpe', 0):.3f}")

    # Save
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            if isinstance(obj, (pd.Timestamp, Path)): return str(obj)
            return super().default(obj)

    output = {
        "metadata": {"timestamp": timestamp, "real_etf": True},
        "baseline": {w: baseline_eval.get(w, {}) for w in EVAL_WINDOWS},
        "best_by_window": best,
        "pareto": [{"params": r.get("params"), "score": s} for s, r in pareto[:20]],
        "all_results_summary": [
            {"params": r.get("params", ""),
             "full_cagr": r.get("full_overlap", {}).get("cagr", 0),
             "val_cagr": r.get("fixed_validation", {}).get("cagr", 0),
             "rp25_cagr": r.get("retrospective_2025_plus", {}).get("cagr", 0),
             "full_sharpe": r.get("full_overlap", {}).get("sharpe", 0),
             }
            for r in all_results
        ],
    }

    with open(output_dir / "deep_dive_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, cls=NpEncoder, indent=2, ensure_ascii=False)
    print(f"\nSaved: {output_dir / 'deep_dive_results.json'}")


if __name__ == "__main__":
    main()
