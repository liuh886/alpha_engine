"""Corrected QQQR optimization — uses report daily returns, proper window validation.

Fixes:
- Use daily report['gross_return'] directly, not sparse position prices
- Actual turnover-based cost from weight changes
- Proper window splitting (not full-period)
- #770-aligned methodology
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

COST_BPS = 10.0
ASSETS = ["QQQI", "QQQ", "TQQQ", "SGOV"]
# Windows from formal backtest date_range
WINDOW_SPLITS = {
    "2024H1": ("2024-01-30", "2024-06-30"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025H1": ("2025-01-01", "2025-06-30"),
    "2025H2": ("2025-07-01", "2025-12-31"),
}


def load_v43():
    d = json.loads(Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json").read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"])
    report["date"] = pd.to_datetime(report["date"])
    report = report.set_index("date")
    return report


def compute_window(report, s0, s1, s2, panic, defense, window_label, cost_bps):
    """Compute strategy returns for a specific window using ACTUAL daily report data."""
    ws, we = WINDOW_SPLITS[window_label]
    daily = report.loc[ws:we].copy()
    if len(daily) == 0:
        return None

    w = pd.DataFrame(0.0, index=daily.index, columns=ASSETS)
    for i in range(len(daily)):
        st = int(daily["position_state"].iloc[i])
        ws_dict = {0: s0, 1: s1, 2: s2}.get(st, s0)
        for a in ASSETS:
            w.iloc[i, w.columns.get_loc(a)] = ws_dict.get(a, 0.0)
        if daily["panic_repair_active"].iloc[i] and panic > 0 and st in (0, 1):
            ct = ws_dict.get("TQQQ", 0.0)
            cq = ws_dict.get("QQQI", 0.0)
            b = min(panic, cq)
            w.iloc[i, w.columns.get_loc("TQQQ")] = ct + b
            w.iloc[i, w.columns.get_loc("QQQI")] = cq - b
        if daily["slow_bear_defense_active"].iloc[i]:
            qp, sp = defense
            w.iloc[i, w.columns.get_loc("QQQI")] = qp
            w.iloc[i, w.columns.get_loc("SGOV")] = sp
            w.iloc[i, w.columns.get_loc("QQQ")] = 0.0
            w.iloc[i, w.columns.get_loc("TQQQ")] = 0.0

    # Use report's pre-computed individual asset returns
    # The report has weight_QQQ, weight_QQQI, etc. and gross_return
    # We can compute: our gross = sum(w_i * (report_return_i))
    # Since we don't have individual returns, use the existing weights as a proxy:
    # our_gross = report['gross_return'] * (our_total_exposure / report_total_exposure)
    # This is approximate but preserves the actual market moves

    # Better: reconstruct from benchmark returns
    # For a first-order correction: use the report's actual daily returns scaled by our weight differences
    report_exposure = daily["weight_QQQ"] + daily["weight_QQQI"] + daily["weight_TQQQ"]
    our_exposure = w["QQQ"] + w["QQQI"] + w["TQQQ"]

    # Gross return = daily gross * (our_exposure / report_exposure) approximately
    # This is still approximate but much better than position price reconstruction
    gross_ret = daily["gross_return"] * (our_exposure / report_exposure.replace(0, 1.0))

    # Turnover-based cost
    wc = w.diff().abs().sum(axis=1)
    wc.iloc[0] = w.iloc[0].abs().sum()
    tc = wc * cost_bps / 10000.0

    net_ret = gross_ret.values - tc.values
    eq = (1.0 + pd.Series(net_ret, index=daily.index)).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    sc = float(eq.iloc[-1] - 1.0)

    # Benchmark: QQQ from report
    bc = float(daily["bench_qqq"].iloc[-1] / daily["bench_qqq"].iloc[0] - 1.0)
    re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0

    return {"relative_excess": re, "max_drawdown": dd, "strategy_compound": sc,
            "benchmark_compound": bc, "n_periods": len(daily),
            "total_cost": float(tc.sum()), "total_turnover": float(wc.sum())}


def run():
    report = load_v43()
    print(f"Loaded {len(report)} daily records")

    s0b = {"QQQI": 0.5, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.5}
    s1b = {"QQQI": 0.9, "QQQ": 0.1, "TQQQ": 0.0, "SGOV": 0.0}
    s2b = {"QQQI": 0.0, "QQQ": 0.0, "TQQQ": 1.0, "SGOV": 0.0}

    # Configs: select subset of most promising from earlier exploration
    configs = [
        ("v43_baseline", s0b, s1b, s2b, 0.0, (0.75, 0.25)),
        ("sgov70_s1_100", {"QQQI": 0.3, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.7},
         {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
        ("sgov60_s1_95", {"QQQI": 0.4, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.6},
         {"QQQI": 0.95, "QQQ": 0.05, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
        ("sgov50_s1_90", s0b, s1b, s2b, 0.0, (0.75, 0.25)),
        ("no_sgov_s1_100", {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
         {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
    ]

    all_results = []
    for win in WINDOW_SPLITS:
        for cid, s0, s1, s2, panic, defense in configs:
            for cost in (10, 20, 40):
                r = compute_window(report, s0, s1, s2, panic, defense, win, cost)
                if r is None:
                    continue
                r["config"] = cid
                r["window"] = win
                r["cost_bps"] = cost
                all_results.append(r)

        w_results = [r for r in all_results if r["window"] == win and r["cost_bps"] == 10]
        w_results.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"[{win}] top-3: " + " | ".join(
            f"{r['config']}: exc={r['relative_excess']:.3f} dd={r['max_drawdown']:.3f}"
            for r in w_results[:3]
        ))

    # Aggregate
    by_c = {}
    for r in all_results:
        cid, cost = r["config"], r["cost_bps"]
        by_c.setdefault(cid, {}).setdefault(cost, {})[r["window"]] = r

    agg = []
    for cid, cdata in by_c.items():
        if 10 not in cdata or len(cdata[10]) < 4:
            continue
        o10 = [cdata[10][w] for w in WINDOW_SPLITS]
        sn = math.prod(1.0 + r["strategy_compound"] for r in o10)
        bn = math.prod(1.0 + r["benchmark_compound"] for r in o10)
        ce10 = sn / bn - 1.0
        dd = min(r["max_drawdown"] for r in o10)

        ce40 = None
        if 40 in cdata and len(cdata[40]) >= 4:
            o40 = [cdata[40][w] for w in WINDOW_SPLITS]
            ce40 = math.prod(1.0 + r["strategy_compound"] for r in o40) / math.prod(
                1.0 + r["benchmark_compound"] for r in o40) - 1.0

        agg.append({"config": cid, "exc10": ce10, "exc40": ce40, "dd": dd})

    agg.sort(key=lambda r: r["exc10"], reverse=True)
    bl = next((r for r in agg if r["config"] == "v43_baseline"), None)

    print(f"\n{'Config':<25s} {'Exc@10':>8s} {'DD':>8s} {'Exc@40':>8s} {'Calmar':>8s}")
    print("-" * 65)
    for r in agg:
        exc40s = f'{r["exc40"]:.4f}' if r["exc40"] else 'N/A'
        cm = float(r["exc10"]) / abs(float(r["dd"])) if r["dd"] != 0 else 0
        print(f'{r["config"]:<25s} {r["exc10"]:>8.4f} {r["dd"]:>8.4f} {exc40s:>8s} {cm:>8.4f}')

    out = Path("artifacts/optimization/qqqr_corrected_v1/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2, default=str))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    run()
