"""Isolated experiments: USx, BYD, QQQR — one-layer-per-candidate discipline.

USx: calibration-only + factor-delta vs #770 certified r11_sampled
BYD: hysteresis-only + defense-weight-only vs v1.3 baseline
QQQR: honest baseline documentation (no individual ETF prices = cannot optimize)
"""
from __future__ import annotations

import hashlib, json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.foundation import DataFoundation
from src.research.daily_ranker import prepare_ranker_frame
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

RET = "Ref($close, -10) / $close - 1"
WINS = ("2024H1", "2024H2", "2025H1", "2025H2")
TRAIN = {"2024H1": ("2021-01-01", "2023-12-31"), "2024H2": ("2021-01-01", "2024-06-30"),
         "2025H1": ("2021-01-01", "2024-12-31"), "2025H2": ("2021-01-01", "2025-06-30")}


# ============================================================
# USx isolated experiment
# ============================================================
def usx_isolated():
    """Layer 1: baseline (#770 r11_sampled). Layer 2: calibration-only delta."""
    print("=" * 60)
    print("USx Isolated Experiment")
    print("=" * 60)

    # #770 certified r11_sampled calibration
    r11_cal = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31, "max_depth": 0,
               "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 0.8,
               "colsample_bytree": 0.8, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}

    candidates = [
        ("us_baseline_r11", ["momentum_volatility_volume"], {**r11_cal}, 15, 4, "baseline",
         "#770 certified r11_sampled: 200r, lr=0.05, subsample/colsample=0.8, cap=4"),
        ("us_calibration_delta", ["momentum_volatility_volume"],
         {**r11_cal, "num_boost_round": 300, "learning_rate": 0.03}, 15, 4, "challenger",
         "CALIBRATION-ONLY delta: 300r, lr=0.03 vs baseline 200r, lr=0.05"),
    ]

    foundation = DataFoundation(
        market="us", benchmark="QQQ", provider_uri="data/providers/us",
        factor_library_path="configs/factor_libraries/ohlcv.yaml",
        universe_config_path="configs/research_universes/us_selected_equities_v2.yaml",
        sector_config_path="configs/research_classifications/us87_sector_industry_v1.yaml",
    )
    foundation.initialize()
    smap = foundation.sector_map

    config_exprs = {}
    for cid, groups, _, _, _, _, _ in candidates:
        config_exprs[cid] = foundation.factor_expressions(list(groups))
    all_e = set(); [all_e.update(v) for v in config_exprs.values()]
    all_exprs = sorted(all_e); e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[usx] {len(all_exprs)} expressions, {len(foundation.symbols)} symbols, {len(smap)} sectors")

    all_r = []; score_id = defaultdict(dict)

    for win in WINS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        f, ret, bm, ed = wdata["features"], wdata["returns"], wdata["benchmark"], wdata["eval_dates"]
        d = f.index.get_level_values("datetime")
        tm = (d >= pd.Timestamp(ts)) & (d <= pd.Timestamp(te)); testm = d.isin(ed)
        ret_test = ret.loc[testm].copy()

        for cid, groups, cal_d, tn, mps, role, desc in candidates:
            ei = [e2i[e] for e in config_exprs[cid]]; nf = len(ei)
            cf = f.iloc[:, ei].copy(); cf.columns = [f"f{i}" for i in range(nf)]
            cft = cf.loc[tm].copy(); rt = ret.loc[tm].copy()
            cft, rt = purge_training_tail(cft, rt, holding_days=10)
            v, _ = validate_no_nan_inputs(cft, context=f"{win}/{cid}")
            if not v: continue
            dc = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31, "max_depth": 0,
                  "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 1.0,
                  "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
            cal = XGBNativeCalibration.from_dict({**dc, **cal_d})
            xr, yr, gr = prepare_ranker_frame(cft, rt)
            fitted = fit_xgb_native_daily_ranker(xr, yr, gr, calibration=cal)
            cfe = cf.loc[testm].copy(); scores = predict_xgb_native_daily_ranker(fitted, cfe)
            score_id[cid][win] = hashlib.sha256(scores["score"].values.tobytes()).hexdigest()[:16]

            for cost in (20, 40, 60):
                rd = [ed[i] for i in range(0, len(ed), 10)]; pr, tos, pw = [], [], None
                for dt in rd:
                    try:
                        ds = scores.xs(dt, level="datetime"); dr = ret_test.xs(dt, level="datetime")
                    except KeyError: continue
                    sel = _select_strict(ds["score"], smap, tn, mps)
                    sel = [s for s in sel if s in dr.index]
                    if not sel: continue
                    n = len(sel); cw = {s: 1.0/n for s in sel}
                    if pw: to = sum(abs(cw.get(s,0)-pw.get(s,0)) for s in set(list(pw)+list(cw)))
                    else: to = 1.0
                    pr.append(float(dr.loc[sel, "return"].mean()) - to * cost / 10000.0)
                    tos.append(to); pw = cw
                if not pr: continue
                ps = pd.Series(pr, index=pd.DatetimeIndex([rd[i] for i in range(len(pr))]))
                cm = ps.index.intersection(bm.index)
                if len(cm)==0: continue
                pa = ps[cm]; ba = bm.loc[cm,"return"]
                sc = float(np.prod(1.0+pa)-1.0); bc = float(np.prod(1.0+ba)-1.0)
                dd = float(((1.0+pa).cumprod()/(1.0+pa).cumprod().cummax()-1.0).min())
                re = (1.0+sc)/(1.0+bc)-1.0 if bc>-1 else 0.0
                all_r.append({"c":cid,"w":win,"cost":cost,"re":re,"dd":dd,"sc":sc,"bc":bc,"to":float(np.mean(tos))})

    return _aggregate_and_report(all_r, candidates, score_id, "usx_isolated_v1", "artifacts/optimization/usx_isolated_v1")


# ============================================================
# BYD isolated experiment
# ============================================================
def byd_isolated():
    """Layer 1: v1.3 baseline. Layer 2: hysteresis-only. Layer 3: defense-weight-only."""
    print("\n" + "=" * 60)
    print("BYD Isolated Experiment")
    print("=" * 60)

    WSPLITS = {"2024H1": ("2024-01-01", "2024-06-30"), "2024H2": ("2024-07-01", "2024-12-31"),
               "2025H1": ("2025-01-01", "2025-06-30"), "2025H2": ("2025-07-01", "2025-12-31")}

    d = json.loads(Path("data/research/formal_backtests/byd_v1_3_recovery_event_low_vol_confirmation_v1.json").read_text(encoding="utf-8"))
    rpt = pd.DataFrame(d["report"]); rpt["date"] = pd.to_datetime(rpt["date"]); rpt = rpt.set_index("date")

    def ms(m20, fi, cp, mf):
        if m20 <= 0: return 0.0, 0.0
        s = min(1.0, m20 / fi) ** cp; return s, s * mf

    candidates = [
        ("byd_v13_baseline", 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0, "baseline",
         "v1.3 baseline: def=75%, no hysteresis"),
        ("byd_hysteresis_only", 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05, "challenger",
         "HYSTERESIS-ONLY delta: +5% entry, -5% exit, same def=75%"),
        ("byd_defense_only", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0, "challenger",
         "DEFENSE-ONLY delta: def=0%, no hysteresis"),
    ]

    all_r = []
    for wl in WSPLITS:
        ws, we = WSPLITS[wl]; daily = rpt.loc[ws:we].copy()
        if len(daily) == 0: continue

        for cid, db, ob, em, fi, cp, mf, me, mx, role, desc in candidates:
            for cost in (20, 40, 60):
                in_off, wb, wef = False, [], []
                for i in range(len(daily)):
                    m20 = float(daily["momentum_20"].iloc[i])
                    s, inc = ms(max(0.0, m20), fi, cp, mf)
                    if not in_off and m20 > me: in_off = True
                    elif in_off and m20 <= mx: in_off = False
                    if in_off:
                        tb = min(ob + inc, em); wb.append(tb); wef.append(0.0)
                    else:
                        wb.append(db); wef.append(1.0 - db)

                re_exp = daily["weight_BYD"] + daily.get("weight_515180", 0)
                oe = pd.Series(wb, index=daily.index) + pd.Series(wef, index=daily.index)
                ratio = oe / re_exp.replace(0, 1.0).clip(0.01)
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
                re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
                all_r.append({"c": cid, "w": wl, "cost": cost, "re": re, "dd": dd, "sc": sc, "bc": bc,
                              "to": float(wch.sum()), "desc": desc})

    return _aggregate_and_report(all_r,
        [(c[0],) + c[5:7] + c[8:10] for c in candidates],  # (cid, role, desc)
        {}, "byd_isolated_v1", "artifacts/optimization/byd_isolated_v1")


# ============================================================
# QQQR — honest baseline documentation
# ============================================================
def qqqr_isolated():
    """Document baseline only. Cannot optimize without individual ETF daily prices."""
    print("\n" + "=" * 60)
    print("QQQR Isolated Experiment — HONEST LIMITATION")
    print("=" * 60)

    WSPLITS = {"2024H1": ("2024-01-30", "2024-06-30"), "2024H2": ("2024-07-01", "2024-12-31"),
               "2025H1": ("2025-01-01", "2025-06-30"), "2025H2": ("2025-07-01", "2025-12-31")}

    d = json.loads(Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json").read_text(encoding="utf-8"))
    rpt = pd.DataFrame(d["report"]); rpt["date"] = pd.to_datetime(rpt["date"]); rpt = rpt.set_index("date")

    print(f"[qqqr] {len(rpt)} daily records, columns: {list(rpt.columns)[:10]}...")
    print(f"[qqqr] Has individual asset returns: {'QQQ_return' in rpt.columns or 'qqq_return' in rpt.columns}")
    print(f"[qqqr] LIMITATION: report only has aggregate gross_return, not per-asset returns.")
    print(f"[qqqr] Cannot back out individual QQQ/QQQI/TQQQ returns from aggregate data.")
    print(f"[qqqr] Any weight overlay is approximate and unreliable for gate-level decisions.")

    # Document baseline only
    baseline_metrics = {}
    for wl in WSPLITS:
        ws, we = WSPLITS[wl]; daily = rpt.loc[ws:we]
        if len(daily) == 0: continue
        sc = float(daily["account"].iloc[-1] / daily["account"].iloc[0] - 1.0)
        bc = float(daily["bench_qqq"].iloc[-1] / daily["bench_qqq"].iloc[0] - 1.0)
        dd = float(daily["drawdown"].min())
        re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
        baseline_metrics[wl] = {"exc": re, "dd": dd, "sc": sc, "bc": bc}
        print(f"  [{wl}] v4.3 baseline: exc={re:.4f} dd={dd:.4f}")

    receipt = {
        "experiment_id": "qqqr_isolated_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "cannot_optimize",
        "reason": "Formal backtest report lacks individual ETF daily returns (QQQ, QQQI, TQQQ, SGOV). Weight overlay approximations are unreliable for gate decisions.",
        "baseline": baseline_metrics,
    }
    out = Path("artifacts/optimization/qqqr_isolated_v1"); out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\nReceipt: {out / 'receipt.json'}")
    return receipt


# ============================================================
# Shared helpers
# ============================================================
def _select_strict(scores, smap, tn, mps):
    ranked = scores.sort_values(ascending=False)
    sel, cnt = [], {}
    for sym, _ in ranked.items():
        s = str(sym); sec = smap.get(s, "Unknown")
        if cnt.get(sec, 0) >= mps: continue
        sel.append(s); cnt[sec] = cnt.get(sec, 0) + 1
        if len(sel) >= tn: break
    return sel


def _aggregate_and_report(all_r, candidates, score_id, exp_id, out_dir):
    byc = defaultdict(lambda: defaultdict(dict))
    for r in all_r:
        byc[r["c"]][r["cost"]][r["w"]] = r

    # Find baseline
    bl_cid = next((c[0] for c in candidates if c[-2] == "baseline"), None)

    agg = []
    for cid_tuple in candidates:
        cid = cid_tuple[0]
        cd = byc.get(cid, {})
        if 20 not in cd or len(cd[20]) != 4:
            print(f"  WARNING: {cid} missing windows")
            continue
        o20 = [cd[20][w] for w in WINS]
        sn = math.prod(1.0 + r["sc"] for r in o20); bn = math.prod(1.0 + r["bc"] for r in o20)
        ce20 = sn / bn - 1.0; dd = min(r["dd"] for r in o20)
        pos = sum(1 for r in o20 if r["re"] > 0)
        ss = max(r["re"] for r in o20) / sum(r["re"] for r in o20 if r["re"] > 0) if sum(r["re"] for r in o20 if r["re"] > 0) > 0 else 1.0
        avg_to = float(np.mean([r.get("to", 0) for r in o20]))
        ce40 = None; ce60 = None
        for cost in (40, 60):
            if cost in cd and len(cd[cost]) == 4:
                oc = [cd[cost][w] for w in WINS]
                snc = math.prod(1.0 + r["sc"] for r in oc); bnc = math.prod(1.0 + r["bc"] for r in oc)
                val = snc / bnc - 1.0
                if cost == 40: ce40 = val
                else: ce60 = val
        pw = {w: {"exc": cd[20][w]["re"], "dd": cd[20][w]["dd"]} for w in WINS if w in cd[20]}
        agg.append({"c": cid, "role": cid_tuple[-2], "desc": cid_tuple[-1],
                     "e20": ce20, "e40": ce40, "e60": ce60, "dd": dd,
                     "pos": pos, "share": ss, "to": avg_to, "pw": pw,
                     "sid": score_id.get(cid, {})})

    agg.sort(key=lambda r: r["e20"], reverse=True)
    bl = next((r for r in agg if r["c"] == bl_cid), None)
    bdd = bl["dd"] if bl else -0.30; bex = bl["e20"] if bl else 0.0

    print(f"\nBaseline ({bl_cid}): DD={bdd:.4f} Exc@20={bex:.4f}")
    print(f"{'Candidate':<35s} {'Exc@20':>8s} {'DD':>8s} {'Exc@60':>8s} {'DD_Impr':>8s} {'Pos':>4s} {'Share':>7s} {'PASS':>5s}")
    print("-" * 110)
    for r in agg:
        ddg = r["dd"] >= bdd + 0.03 or r["dd"] >= -0.22
        eg60 = r["e60"] is not None and r["e60"] > 0
        sg = r["share"] < 0.55; pg = r["pos"] == 4
        # terminal wealth must improve vs baseline
        tw = r["e20"] > bex
        all_p = ddg and eg60 and sg and pg and tw
        e60s = f'{r["e60"]:.4f}' if r["e60"] else 'N/A'
        print(f'{"PASS" if all_p else "FAIL":>5s} {r["c"]:<35s} {r["e20"]:>8.4f} {r["dd"]:>8.4f} {e60s:>8s} {bdd-r["dd"]:>8.4f} {r["pos"]:>4} {r["share"]:>7.4f}')

    # Receipt
    receipt = {
        "experiment_id": exp_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "one-layer-per-candidate, turnover-based cost, strict sector cap",
        "baseline": {"dd": bdd, "exc20": bex}, "results": agg,
    }
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\nReceipt: {out / 'receipt.json'}")
    return agg


if __name__ == "__main__":
    usx_isolated()
    byd_isolated()
    qqqr_isolated()
