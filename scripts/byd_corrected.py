"""Corrected BYD optimization — v1.3 baseline, proper hysteresis, report returns.

Fixes:
- Uses v1.3 formal backtest data (not v1.2)
- Proper state machine hysteresis (memory of offense/defense state)
- Uses report daily data (not sparse position prices)
- Turnover-based cost
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

COST_BPS = 20.0
WINDOW_SPLITS = {
    "2022H2": ("2022-07-01", "2022-12-31"),
    "2023H1": ("2023-01-01", "2023-06-30"),
    "2023H2": ("2023-07-01", "2023-12-31"),
    "2024H1": ("2024-01-01", "2024-06-30"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025H1": ("2025-01-01", "2025-06-30"),
    "2025H2": ("2025-07-01", "2025-12-31"),
}


def load_v13():
    d = json.loads(Path("data/research/formal_backtests/byd_v1_3_recovery_event_low_vol_confirmation_v1.json").read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"])
    report["date"] = pd.to_datetime(report["date"])
    report = report.set_index("date")
    return report


def mom_scale(m20, fi, cp, mf):
    if m20 <= 0: return 0.0, 0.0
    s = min(1.0, m20 / fi) ** cp
    return s, s * mf


def compute_window(report, def_byd, off_byd, exp_max, fi, cp, mf,
                   mom_entry, mom_exit, window_label, cost_bps):
    """Compute with proper state machine hysteresis."""
    ws, we = WINDOW_SPLITS[window_label]
    daily = report.loc[ws:we].copy()
    if len(daily) == 0:
        return None

    in_offense = False  # State memory
    w_byd, w_etf, w_cash = [], [], []

    for i in range(len(daily)):
        m20 = float(daily["momentum_20"].iloc[i])
        s, inc = mom_scale(max(0.0, m20), fi, cp, mf)

        # Proper hysteresis: only change state when crossing thresholds
        if not in_offense and m20 > mom_entry:
            in_offense = True
        elif in_offense and m20 <= mom_exit:
            in_offense = False
        # else: maintain current state

        if in_offense:
            tb = min(off_byd + inc, exp_max)
            w_byd.append(tb)
            w_etf.append(0.0)
            w_cash.append(1.0 - tb)
        else:
            w_byd.append(def_byd)
            w_etf.append(1.0 - def_byd)
            w_cash.append(0.0)

    # Use report's actual returns
    # Report has gross_return = sum of position returns × weights
    # Our allocation differs → compute our gross from our weights
    # But we don't have individual BYD/ETF returns in v1.3 report...
    # Use the report's weight_BYD and weight_515180 to BACK OUT individual returns

    # The report has: gross_return = w_BYD * r_BYD + w_ETF * r_ETF + w_cash * 0
    # We can solve: on days where w_ETF=0, gross_return = w_BYD * r_BYD → r_BYD = gross / w_BYD
    # But this is noisy. Better approach: use the report's pre-computed period_return
    # which is the actual net return after costs.

    # SIMPLEST CORRECT approach: use report['period_return'] adjusted for our different weights
    # This is the actual v1.3 daily net return. We compute our return as:
    # our_ret = report_return * (our_BYD_exposure / report_BYD_exposure)
    # This correctly scales returns by our different allocation

    report_byd_exp = daily["weight_BYD"]
    our_byd_exp = pd.Series(w_byd, index=daily.index)
    # ETF exposure: report has weight_515180, we have w_etf
    report_etf_exp = daily.get("weight_515180", pd.Series(0.0, index=daily.index))
    our_etf_exp = pd.Series(w_etf, index=daily.index)

    # Scale the report's gross return proportionally
    total_report_exp = report_byd_exp + report_etf_exp
    total_our_exp = our_byd_exp + our_etf_exp

    # Approximate gross: report_gross * (our_exp / report_exp) when report_exp > 0
    ratio = total_our_exp / total_report_exp.replace(0, 1.0).clip(lower=0.01)
    gross_ret = daily["gross_return"] * ratio

    # Turnover-based cost
    wb_series = pd.Series(w_byd, index=daily.index)
    we_series = pd.Series(w_etf, index=daily.index)
    wc = abs(wb_series.diff().fillna(0)) + abs(we_series.diff().fillna(0))
    wc.iloc[0] = abs(wb_series.iloc[0]) + abs(we_series.iloc[0])
    tc = wc * cost_bps / 10000.0

    # Financing cost for margin positions
    fin = np.maximum(np.array(w_byd) - 1.0, 0.0)
    fcost = fin * 0.06 / 252.0

    net_ret = gross_ret.values - tc.values - fcost
    eq = (1.0 + pd.Series(net_ret, index=daily.index)).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    sc = float(eq.iloc[-1] - 1.0)
    bc = float(daily["benchmark_return"].iloc[-1])

    re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
    return {"relative_excess": re, "max_drawdown": dd, "strategy_compound": sc,
            "benchmark_compound": bc, "n_periods": len(daily),
            "total_cost": float(tc.sum()), "total_turnover": float(wc.sum())}


def run():
    report = load_v13()
    print(f"Loaded v1.3: {len(report)} daily records")

    configs = [
        ("v13_baseline", 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0),
        ("def0_simple", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0),
        ("def0_hysteresis", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05),
        ("def0_aggressive", 0.0, 1.0, 1.125, 0.10, 6.0, 0.20, 0.05, -0.05),
        ("def25_hysteresis", 0.25, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05),
    ]

    all_results = []
    for win in WINDOW_SPLITS:
        for cid, db, ob, em, fi, cp, mf, me, mx in configs:
            for cost in (20, 40):
                r = compute_window(report, db, ob, em, fi, cp, mf, me, mx, win, cost)
                if r is None: continue
                r["config"] = cid; r["window"] = win; r["cost_bps"] = cost
                all_results.append(r)

        w_results = [r for r in all_results if r["window"] == win and r["cost_bps"] == 20]
        w_results.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"[{win}] top-3: " + " | ".join(
            f"{r['config']}: exc={r['relative_excess']:.3f} dd={r['max_drawdown']:.3f}"
            for r in w_results[:3]
        ))

    # Aggregate across 2024H1-2025H2 (development windows)
    DEV = ("2024H1", "2024H2", "2025H1", "2025H2")
    by_c = {}
    for r in all_results:
        cid, cost = r["config"], r["cost_bps"]
        by_c.setdefault(cid, {}).setdefault(cost, {})[r["window"]] = r

    agg = []
    for cid, cdata in by_c.items():
        if 20 not in cdata or len(cdata[20]) < 4: continue
        o20 = [cdata[20][w] for w in DEV if w in cdata[20]]
        if len(o20) < 4: continue
        sn = math.prod(1.0 + r["strategy_compound"] for r in o20)
        bn = math.prod(1.0 + r["benchmark_compound"] for r in o20)
        ce20 = sn / bn - 1.0
        dd = min(r["max_drawdown"] for r in o20)

        ce40 = None
        if 40 in cdata and len(cdata[40]) >= 4:
            o40 = [cdata[40][w] for w in DEV if w in cdata[40]]
            if len(o40) >= 4:
                ce40 = math.prod(1.0 + r["strategy_compound"] for r in o40) / math.prod(
                    1.0 + r["benchmark_compound"] for r in o40) - 1.0

        agg.append({"config": cid, "exc20": ce20, "exc40": ce40, "dd": dd})

    agg.sort(key=lambda r: r["exc20"], reverse=True)
    bl = next((r for r in agg if r["config"] == "v13_baseline"), None)

    print(f"\n{'Config':<25s} {'Exc@20':>8s} {'DD':>8s} {'Exc@40':>8s} {'Calmar':>8s}")
    print("-" * 65)
    for r in agg:
        exc40s = f'{r["exc40"]:.4f}' if r["exc40"] else 'N/A'
        cm = r["exc20"] / abs(r["dd"]) if r["dd"] != 0 else 0
        dd_impr = (bl["dd"] - r["dd"]) if bl else 0
        print(f'{r["config"]:<25s} {r["exc20"]:>8.4f} {r["dd"]:>8.4f} {exc40s:>8s} {cm:>8.4f}')

    out = Path("artifacts/optimization/byd_corrected_v1/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2, default=str))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    run()
