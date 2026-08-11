"""BYD R51-70: systematic parameter sweep with corrected methodology.

Explores: defense weights, hysteresis thresholds, convex params, expansion max.
All using v1.3 data, proper hysteresis, turnover-based cost.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any
import numpy as np, pandas as pd

COST = 20.0
WINDOW_SPLITS = {"2024H1": ("2024-01-01", "2024-06-30"), "2024H2": ("2024-07-01", "2024-12-31"),
                 "2025H1": ("2025-01-01", "2025-06-30"), "2025H2": ("2025-07-01", "2025-12-31")}

def load_v13():
    d = json.loads(Path("data/research/formal_backtests/byd_v1_3_recovery_event_low_vol_confirmation_v1.json").read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"]); report["date"] = pd.to_datetime(report["date"]); return report.set_index("date")

def ms(m20, fi, cp, mf):
    if m20 <= 0: return 0.0, 0.0
    s = min(1.0, m20 / fi) ** cp; return s, s * mf

def compute(report, db, ob, em, fi, cp, mf, me, mx, wl, cost):
    ws, we = WINDOW_SPLITS[wl]; daily = report.loc[ws:we].copy()
    if len(daily) == 0: return None
    in_off, wb, wef, wc = False, [], [], []
    for i in range(len(daily)):
        m20 = float(daily["momentum_20"].iloc[i])
        s, inc = ms(max(0.0, m20), fi, cp, mf)
        if not in_off and m20 > me: in_off = True
        elif in_off and m20 <= mx: in_off = False
        if in_off:
            tb = min(ob + inc, em); wb.append(tb); wef.append(0.0); wc.append(1.0 - tb)
        else:
            wb.append(db); wef.append(1.0 - db); wc.append(0.0)
    # Scale report returns by our allocation ratio
    re = daily["weight_BYD"] + daily.get("weight_515180", 0)
    oe = pd.Series(wb, index=daily.index) + pd.Series(wef, index=daily.index)
    ratio = oe / re.replace(0, 1.0).clip(0.01)
    gr = daily["gross_return"] * ratio
    wbs = pd.Series(wb, index=daily.index); wes = pd.Series(wef, index=daily.index)
    wch = abs(wbs.diff().fillna(0)) + abs(wes.diff().fillna(0))
    wch.iloc[0] = abs(wbs.iloc[0]) + abs(wes.iloc[0])
    tc = wch * cost / 10000.0
    fin = np.maximum(np.array(wb) - 1.0, 0.0); fc = fin * 0.06 / 252.0
    nr = gr.values - tc.values - fc
    eq = (1.0 + pd.Series(nr, index=daily.index)).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min()); sc = float(eq.iloc[-1] - 1.0)
    bc = float(daily["benchmark_return"].iloc[-1])
    re_exc = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
    return {"re": re_exc, "dd": dd, "sc": sc, "bc": bc, "n": len(daily), "cost": float(tc.sum()), "to": float(wch.sum())}

def run():
    report = load_v13(); print(f"v1.3: {len(report)} records")
    # R51-70: systematic sweep
    configs = []
    # R51-58: Defense sweep 0-50% with hysteresis
    for i, db in enumerate([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.25, 0.15]):
        configs.append((f"r{51+i}_def{int(db*100)}", db, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05))
    # R59-64: Hysteresis threshold sweep
    for i, (me, mx) in enumerate([(0.0, 0.0), (0.02, -0.02), (0.03, -0.03), (0.08, -0.03), (0.05, 0.0), (0.10, -0.05)]):
        configs.append((f"r{59+i}_hyst{int(me*100)}_{int(mx*100)}", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, me, mx))
    # R65-68: Convex params
    for i, (fi, cp, mf) in enumerate([(0.10, 6.0, 0.20), (0.20, 3.0, 0.10), (0.15, 8.0, 0.15), (0.10, 4.0, 0.15)]):
        configs.append((f"r{65+i}_fi{int(fi*100)}_p{int(cp)}_mf{int(mf*1000)}", 0.0, 1.0, 1.125, fi, cp, mf, 0.05, -0.05))
    # R69-70: v1.3 baseline + best combination
    configs.append(("r69_v13_baseline", 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0))
    configs.append(("r70_max", 0.0, 1.0, 1.5, 0.10, 8.0, 0.25, 0.05, -0.05))

    all_r = []
    DEV = ("2024H1", "2024H2", "2025H1", "2025H2")
    for wl in WINDOW_SPLITS:
        for cid, db, ob, em, fi, cp, mf, me, mx in configs:
            for cost in (20, 40):
                r = compute(report, db, ob, em, fi, cp, mf, me, mx, wl, cost)
                if r is None: continue
                r["config"] = cid; r["window"] = wl; r["cost_bps"] = cost
                all_r.append(r)
        w20 = sorted([r for r in all_r if r["window"] == wl and r["cost_bps"] == 20],
                     key=lambda r: r["re"], reverse=True)
        if w20: print(f"[{wl}] {w20[0]['config']}: exc={w20[0]['re']:.4f} dd={w20[0]['dd']:.4f}")

    # Aggregate dev windows
    by_c = {}
    for r in all_r:
        cid, cost = r["config"], r["cost_bps"]
        by_c.setdefault(cid, {}).setdefault(cost, {})[r["window"]] = r
    agg = []
    for cid, cd in by_c.items():
        if 20 not in cd or len(cd[20]) < 4: continue
        o20 = [cd[20][w] for w in DEV if w in cd[20]]
        if len(o20) < 4: continue
        sn = math.prod(1.0 + r["sc"] for r in o20); bn = math.prod(1.0 + r["bc"] for r in o20)
        ce20 = sn / bn - 1.0; dd = min(r["dd"] for r in o20)
        ce40 = None
        if 40 in cd and len(cd[40]) >= 4:
            o40 = [cd[40][w] for w in DEV if w in cd[40]]
            if len(o40) >= 4: ce40 = math.prod(1.0 + r["sc"] for r in o40) / math.prod(1.0 + r["bc"] for r in o40) - 1.0
        agg.append({"config": cid, "exc20": ce20, "exc40": ce40, "dd": dd})

    agg.sort(key=lambda r: r["exc20"], reverse=True)
    bl = next((r for r in agg if r["config"] == "r69_v13_baseline"), None)
    bdd = bl["dd"] if bl else -0.30; bex = bl["exc20"] if bl else 0.0
    print(f"\nBaseline v1.3: DD={bdd:.4f} Exc={bex:.4f}")
    print(f"{'Config':<30s} {'Exc@20':>8s} {'DD':>8s} {'Exc@40':>8s} {'Calmar':>8s}")
    print("-" * 65)
    for r in agg:
        exc40s = f'{r["exc40"]:.4f}' if r["exc40"] else 'N/A'
        cm = r["exc20"] / abs(r["dd"]) if r["dd"] != 0 else 0
        print(f'{r["config"]:<30s} {r["exc20"]:>8.4f} {r["dd"]:>8.4f} {exc40s:>8s} {cm:>8.4f}')

    out = Path("artifacts/optimization/byd_rounds_51_70_v1/results.json"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2, default=str))
    print(f"\nSaved to {out}")

if __name__ == "__main__": run()
