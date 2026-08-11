"""4-model R41-60: corrected methodology, focused exploration.

USx: can we beat #770-certified r11_sampled?
CNx: build on r27_all4_cap4 — calibration + Top-K variants
QQQR: improved return attribution using per-asset weight data
BYD: hysteresis fine-tuning + 2022-2023 validation
"""
from __future__ import annotations

import json, math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

COST_US = 20.0; COST_QQQR = 10.0; COST_BYD = 20.0

# ============================================================
# USx R41-50: challenge #770 r11_sampled
# ============================================================
def usx_rounds():
    from src.data.foundation import DataFoundation
    from src.research.daily_ranker import prepare_ranker_frame
    from src.research.rolling_windows import purge_training_tail
    from src.research.universe_robustness import validate_no_nan_inputs
    from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

    RET = "Ref($close, -10) / $close - 1"
    WINS = ("2024H1", "2024H2", "2025H1", "2025H2")
    TRAIN = {"2024H1": ("2021-01-01", "2023-12-31"), "2024H2": ("2021-01-01", "2024-06-30"),
             "2025H1": ("2021-01-01", "2024-12-31"), "2025H2": ("2021-01-01", "2025-06-30")}

    # r11_sampled (certified baseline) + challengers
    r11_cal = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31, "max_depth": 0,
               "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 0.8,
               "colsample_bytree": 0.8, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}

    configs = [
        # R41-44: different sector caps with r11 calibration
        ("r41_r11_cap3", ["momentum_volatility_volume"], {**r11_cal}, 15, 3),
        ("r42_r11_cap5", ["momentum_volatility_volume"], {**r11_cal}, 15, 5),
        ("r43_r11_top12_cap4", ["momentum_volatility_volume"], {**r11_cal}, 12, 4),
        ("r44_r11_top20_cap4", ["momentum_volatility_volume"], {**r11_cal}, 20, 4),
        # R45-47: extended calibrations
        ("r45_r11_regularized", ["momentum_volatility_volume"],
         {**r11_cal, "reg_alpha": 0.1, "reg_lambda": 2.0}, 15, 4),
        ("r46_r11_300r", ["momentum_volatility_volume"],
         {**r11_cal, "num_boost_round": 300, "learning_rate": 0.03}, 15, 4),
        ("r47_r11_gain5", ["momentum_volatility_volume"],
         {**r11_cal, "n_gain_bins": 5}, 15, 4),
        # R48-50: factor combos
        ("r48_r11_rev", ["momentum_volatility_volume"], {**r11_cal}, 15, 4),
        ("r49_r11_meanrev", ["momentum_volatility_volume"], {**r11_cal}, 15, 4),
        ("r50_r11_baseline", ["momentum_volatility_volume"], {**r11_cal}, 15, 4),
    ]

    # Add reversal/mean_reversion factors for r48/r49
    REV_IDS = ["ohlcv.reversal.inv_ret_1d", "ohlcv.reversal.inv_ret_3d", "ohlcv.reversal.inv_ret_5d"]
    MEAN_IDS = ["ohlcv.mean_reversion.close_vs_ma_5d", "ohlcv.mean_reversion.close_vs_ma_10d", "ohlcv.mean_reversion.close_vs_ma_20d"]

    foundation = DataFoundation(market="us", benchmark="QQQ", provider_uri="data/providers/us",
                                 factor_library_path="configs/factor_libraries/ohlcv.yaml",
                                 universe_config_path="configs/research_universes/us_selected_equities_v2.yaml",
                                 sector_config_path="configs/research_classifications/us87_sector_industry_v1.yaml")
    foundation.initialize()
    smap = foundation.sector_map

    def get_exprs(groups, extra_ids=None):
        exprs = foundation.factor_expressions(list(groups))
        if extra_ids:
            raw = yaml.safe_load(Path("configs/factor_libraries/ohlcv.yaml").read_text(encoding="utf-8"))
            ff = raw.get("factors", {})
            for fid in extra_ids:
                if fid in ff and ff[fid]["expression"] not in exprs:
                    exprs.append(ff[fid]["expression"])
        return exprs

    import yaml
    config_exprs = {}
    for cid, groups, _, _, _ in configs:
        if cid == "r48_r11_rev":
            config_exprs[cid] = get_exprs(groups, REV_IDS)
        elif cid == "r49_r11_meanrev":
            config_exprs[cid] = get_exprs(groups, MEAN_IDS)
        else:
            config_exprs[cid] = get_exprs(groups)

    all_e = set(); [all_e.update(v) for v in config_exprs.values()]
    all_exprs = sorted(all_e); e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[usx] {len(all_exprs)} expressions, {len(configs)} configs")

    def select_strict(scores, sm, tn, mps):
        if mps is None: return list(scores.nlargest(tn).index)
        ranked = scores.sort_values(ascending=False)
        sel, cnt = [], {}
        for sym, _ in ranked.items():
            s = str(sym); sec = sm.get(s, "Unknown")
            if cnt.get(sec, 0) >= mps: continue
            sel.append(s); cnt[sec] = cnt.get(sec, 0) + 1
            if len(sel) >= tn: break
        return sel

    all_r = []
    for win in WINS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        f, ret, bm, ed = wdata["features"], wdata["returns"], wdata["benchmark"], wdata["eval_dates"]
        d = f.index.get_level_values("datetime")
        tm = (d >= pd.Timestamp(ts)) & (d <= pd.Timestamp(te))
        testm = d.isin(ed)

        for cid, groups, cal_d, tn, mps in configs:
            ei = [e2i[e] for e in config_exprs[cid]]
            cf = f.iloc[:, ei].copy(); cf.columns = [f"f{i}" for i in range(len(ei))]
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
            rte = ret.loc[testm].copy()

            for cost in (20, 60):
                rd = [ed[i] for i in range(0, len(ed), 10)]
                pr, tos, pw = [], [], None
                for dt in rd:
                    try:
                        ds = scores.xs(dt, level="datetime"); dr = rte.xs(dt, level="datetime")
                    except KeyError: continue
                    sel = select_strict(ds["score"], smap, tn, mps)
                    sel = [s for s in sel if s in dr.index]
                    if not sel: continue
                    n = len(sel); cw = {s: 1.0/n for s in sel}
                    if pw is not None:
                        alls = set(list(pw) + list(cw))
                        to = sum(abs(cw.get(s, 0) - pw.get(s, 0)) for s in alls)
                    else: to = 1.0
                    gr_ret = float(dr.loc[sel, "return"].mean())
                    pr.append(gr_ret - to * cost / 10000.0)
                    tos.append(to); pw = cw
                if not pr: continue
                ps = pd.Series(pr, index=pd.DatetimeIndex([rd[i] for i in range(len(pr))]))
                cm = ps.index.intersection(bm.index)
                if len(cm) == 0: continue
                pa = ps[cm]; ba = bm.loc[cm, "return"]
                sc = float(np.prod(1.0+pa)-1.0); bc = float(np.prod(1.0+ba)-1.0)
                dd = float(((1.0+pa).cumprod()/(1.0+pa).cumprod().cummax()-1.0).min())
                re = (1.0+sc)/(1.0+bc)-1.0 if bc>-1 else 0.0
                all_r.append({"c": cid, "w": win, "cost": cost, "re": re, "dd": dd, "sc": sc, "bc": bc, "to": float(np.mean(tos))})

    # Aggregate
    byc = defaultdict(lambda: {"w20": {}, "w60": {}})
    for r in all_r:
        k = "w20" if r["cost"] == 20 else "w60"; byc[r["c"]][k][r["w"]] = r
    agg = []
    for cid, cd in byc.items():
        if len(cd["w20"]) != 4: continue
        o20 = [cd["w20"][w] for w in WINS]
        sn = math.prod(1.0+r["sc"] for r in o20); bn = math.prod(1.0+r["bc"] for r in o20)
        ce20 = sn/bn-1.0; dd = min(r["dd"] for r in o20)
        pos = sum(1 for r in o20 if r["re"] > 0)
        ss = max(r["re"] for r in o20)/sum(r["re"] for r in o20 if r["re"]>0) if sum(r["re"] for r in o20 if r["re"]>0)>0 else 1.0
        ce60 = None
        if len(cd["w60"]) == 4:
            o60 = [cd["w60"][w] for w in WINS]
            ce60 = math.prod(1.0+r["sc"] for r in o60)/math.prod(1.0+r["bc"] for r in o60)-1.0
        agg.append({"c": cid, "e20": ce20, "e60": ce60, "dd": dd, "pos": pos, "share": ss})

    agg.sort(key=lambda r: r["e20"], reverse=True)
    bl = next((r for r in agg if r["c"] == "r50_r11_baseline"), None)
    bdd = bl["dd"] if bl else -0.30; bex = bl["e20"] if bl else 0.0
    print(f"\nBaseline r11_sampled: DD={bdd:.4f} Exc={bex:.4f}")
    for r in agg:
        e60s = f'{r["e60"]:.4f}' if r["e60"] else 'N/A'
        ddg = r["dd"] >= bdd + 0.03 or r["dd"] >= -0.22
        eg = r["e20"] >= 0.90 * bex; e60g = r["e60"] is not None and r["e60"] > 0
        sg = r["share"] < 0.55; pg = r["pos"] == 4
        ap = ddg and eg and e60g and sg and pg
        print(f'{"PASS" if ap else "FAIL":>5s} {r["c"]:<25s} e20={r["e20"]:.4f} dd={r["dd"]:.4f} e60={e60s} share={r["share"]:.4f}')

    return agg


# ============================================================
# QQQR R41-50: improved return attribution
# ============================================================
def qqqr_rounds():
    """Use per-asset weight columns and gross_return to back out individual returns."""
    ASSETS = ["QQQI", "QQQ", "TQQQ", "SGOV"]
    WSPLITS = {"2024H1": ("2024-01-30", "2024-06-30"), "2024H2": ("2024-07-01", "2024-12-31"),
               "2025H1": ("2025-01-01", "2025-06-30"), "2025H2": ("2025-07-01", "2025-12-31")}

    d = json.loads(Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json").read_text(encoding="utf-8"))
    rpt = pd.DataFrame(d["report"]); rpt["date"] = pd.to_datetime(rpt["date"]); rpt = rpt.set_index("date")

    # Back out individual asset returns from weight columns and gross_return
    # On days where SGOV weight = 0: gross = w_QQQ*r_QQQ + w_QQQI*r_QQQI + w_TQQQ*r_TQQQ
    # We have 3 unknowns but only 1 equation per day.
    # Use the report's pre-computed period_return directly as the net strategy return,
    # and compute our strategy's NET return delta based on weight differences.
    # This is approximate but honest about the approximation.

    s0b = {"QQQI": 0.5, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.5}
    s1b = {"QQQI": 0.9, "QQQ": 0.1, "TQQQ": 0.0, "SGOV": 0.0}
    s2b = {"QQQI": 0.0, "QQQ": 0.0, "TQQQ": 1.0, "SGOV": 0.0}

    configs = [
        ("q41_v43_baseline", s0b, s1b, s2b, 0.0, (0.75, 0.25)),
        ("q42_sgov70_s1_100", {"QQQI": 0.3, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.7},
         {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
        ("q43_no_sgov_s1_100", {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
         {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
        ("q44_sgov60_s1_95", {"QQQI": 0.4, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.6},
         {"QQQI": 0.95, "QQQ": 0.05, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
        ("q45_sgov80_s1_100", {"QQQI": 0.2, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.8},
         {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}, s2b, 0.0, (0.75, 0.25)),
    ]

    def compute_q(rpt, s0, s1, s2, panic, defense, wl, cost):
        ws, we = WSPLITS[wl]; daily = rpt.loc[ws:we].copy()
        if len(daily) == 0: return None

        # Build our weights
        w = pd.DataFrame(0.0, index=daily.index, columns=ASSETS)
        for i in range(len(daily)):
            st = int(daily["position_state"].iloc[i])
            wd = {0: s0, 1: s1, 2: s2}.get(st, s0)
            for a in ASSETS: w.iloc[i, w.columns.get_loc(a)] = wd.get(a, 0.0)
            if daily["panic_repair_active"].iloc[i] and panic > 0 and st in (0, 1):
                ct = wd.get("TQQQ", 0.0); cq = wd.get("QQQI", 0.0)
                b = min(panic, cq); w.iloc[i, w.columns.get_loc("TQQQ")] = ct + b
                w.iloc[i, w.columns.get_loc("QQQI")] = cq - b
            if daily["slow_bear_defense_active"].iloc[i]:
                qp, sp = defense
                w.iloc[i, w.columns.get_loc("QQQI")] = qp; w.iloc[i, w.columns.get_loc("SGOV")] = sp
                w.iloc[i, w.columns.get_loc("QQQ")] = 0.0; w.iloc[i, w.columns.get_loc("TQQQ")] = 0.0

        # Use report's period_return (net) + our weight delta × gross_return
        # delta_ret = (our_weight_i - report_weight_i) × report_gross / report_exposure
        # This attributes return differences to weight differences proportionally
        report_weights = pd.DataFrame({
            "QQQI": daily["weight_QQQI"], "QQQ": daily["weight_QQQ"],
            "TQQQ": daily["weight_TQQQ"], "SGOV": daily["weight_SGOV"]
        }, index=daily.index)
        report_exp = report_weights[["QQQI", "QQQ", "TQQQ"]].sum(axis=1)
        our_exp = w[["QQQI", "QQQ", "TQQQ"]].sum(axis=1)

        # Weight delta impact
        weight_delta_impact = (our_exp - report_exp) * daily["gross_return"] / report_exp.replace(0, 1.0).clip(0.01)

        # Our gross = report period_return + weight delta impact
        # HONEST: this is approximate. Without individual asset returns, exact decomposition is impossible.
        our_gross = daily["period_return"] + weight_delta_impact

        # Turnover cost for our weights
        wc = w.diff().abs().sum(axis=1); wc.iloc[0] = w.iloc[0].abs().sum()
        tc = wc * cost / 10000.0

        nr = our_gross.values - tc.values
        eq = (1.0 + pd.Series(nr, index=daily.index)).cumprod()
        dd = float((eq / eq.cummax() - 1.0).min()); sc = float(eq.iloc[-1] - 1.0)
        bc = float(daily["bench_qqq"].iloc[-1] / daily["bench_qqq"].iloc[0] - 1.0)
        re_exc = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
        return {"re": re_exc, "dd": dd, "sc": sc, "bc": bc, "n": len(daily)}

    all_r = []
    for wl in WSPLITS:
        for cid, s0, s1, s2, panic, defense in configs:
            for cost in (10, 20):
                r = compute_q(rpt, s0, s1, s2, panic, defense, wl, cost)
                if r is None: continue
                r["c"] = cid; r["w"] = wl; r["cost"] = cost; all_r.append(r)
        w10 = sorted([r for r in all_r if r["w"] == wl and r["cost"] == 10], key=lambda r: r["re"], reverse=True)
        if w10: print(f"[qqqr:{wl}] {w10[0]['c']}: re={w10[0]['re']:.4f} dd={w10[0]['dd']:.4f}")

    byc = defaultdict(lambda: {"w10": {}, "w20": {}})
    for r in all_r:
        k = "w10" if r["cost"] == 10 else "w20"; byc[r["c"]][k][r["w"]] = r
    agg = []
    WINS_Q = ("2024H1", "2024H2", "2025H1", "2025H2")
    for cid, cd in byc.items():
        if len(cd["w10"]) != 4: continue
        o10 = [cd["w10"][w] for w in WINS_Q]
        sn = math.prod(1.0+r["sc"] for r in o10); bn = math.prod(1.0+r["bc"] for r in o10)
        ce10 = sn/bn-1.0; dd = min(r["dd"] for r in o10)
        agg.append({"c": cid, "e10": ce10, "dd": dd})

    agg.sort(key=lambda r: r["e10"], reverse=True)
    print(f"\nQQQR R41-50:")
    for r in agg: print(f"  {r['c']:<30s} e10={r['e10']:.4f} dd={r['dd']:.4f}")
    return agg


# ============================================================
# BYD R71-80: hysteresis fine-tuning + 2022-2023 validation
# ============================================================
def byd_rounds():
    WSPLITS = {"2022H2": ("2022-07-01", "2022-12-31"), "2023H1": ("2023-01-01", "2023-06-30"),
               "2023H2": ("2023-07-01", "2023-12-31"),
               "2024H1": ("2024-01-01", "2024-06-30"), "2024H2": ("2024-07-01", "2024-12-31"),
               "2025H1": ("2025-01-01", "2025-06-30"), "2025H2": ("2025-07-01", "2025-12-31")}
    DEV = ("2024H1", "2024H2", "2025H1", "2025H2")
    ALL = ("2022H2", "2023H1", "2023H2", "2024H1", "2024H2", "2025H1", "2025H2")

    d = json.loads(Path("data/research/formal_backtests/byd_v1_3_recovery_event_low_vol_confirmation_v1.json").read_text(encoding="utf-8"))
    rpt = pd.DataFrame(d["report"]); rpt["date"] = pd.to_datetime(rpt["date"]); rpt = rpt.set_index("date")

    def ms(m20, fi, cp, mf):
        if m20 <= 0: return 0.0, 0.0
        s = min(1.0, m20 / fi) ** cp; return s, s * mf

    # R71-80: finer hysteresis + expansion + convex combos
    configs = [
        ("r71_def0_hyst10_0", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, 0.10, 0.0),
        ("r72_def0_hyst15_-5", 0.0, 1.0, 1.125, 0.15, 4.0, 0.125, 0.15, -0.05),
        ("r73_def0_exp150_hyst5", 0.0, 1.0, 1.50, 0.15, 4.0, 0.125, 0.05, -0.05),
        ("r74_def0_exp125_pow6", 0.0, 1.0, 1.25, 0.10, 6.0, 0.20, 0.05, -0.05),
        ("r75_def0_exp150_pow8", 0.0, 1.0, 1.50, 0.10, 8.0, 0.25, 0.05, -0.05),
        ("r76_def10_hyst5", 0.10, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05),
        ("r77_def20_hyst5", 0.20, 1.0, 1.125, 0.15, 4.0, 0.125, 0.05, -0.05),
        ("r78_def0_hyst5_pow6", 0.0, 1.0, 1.125, 0.15, 6.0, 0.125, 0.05, -0.05),
        ("r79_def0_hyst5_mf200", 0.0, 1.0, 1.125, 0.15, 4.0, 0.20, 0.05, -0.05),
        ("r70_v13_baseline", 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, 0.0, 0.0),
    ]

    def compute_b(rpt, db, ob, em, fi, cp, mf, me, mx, wl, cost):
        ws, we = WSPLITS[wl]; daily = rpt.loc[ws:we].copy()
        if len(daily) == 0: return None
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
        re_exc = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
        return {"re": re_exc, "dd": dd, "sc": sc, "bc": bc}

    all_r = []
    for wl in ALL:
        for cid, db, ob, em, fi, cp, mf, me, mx in configs:
            for cost in (20, 40):
                r = compute_b(rpt, db, ob, em, fi, cp, mf, me, mx, wl, cost)
                if r is None: continue
                r["c"] = cid; r["w"] = wl; r["cost"] = cost; all_r.append(r)

    # Aggregate dev windows
    byc = defaultdict(lambda: {"w20": {}, "w40": {}})
    for r in all_r:
        k = "w20" if r["cost"] == 20 else "w40"; byc[r["c"]][k][r["w"]] = r
    agg = []
    for cid, cd in byc.items():
        if 20 not in cd or len(cd[20]) < 4: continue
        o20 = [cd[20][w] for w in DEV if w in cd[20]]
        if len(o20) < 4: continue
        sn = math.prod(1.0+r["sc"] for r in o20); bn = math.prod(1.0+r["bc"] for r in o20)
        ce20 = sn/bn-1.0; dd = min(r["dd"] for r in o20)

        # Full period
        o20_all = [cd[20][w] for w in ALL if w in cd[20]]
        sn_all = math.prod(1.0+r["sc"] for r in o20_all); bn_all = math.prod(1.0+r["bc"] for r in o20_all)
        ce20_all = sn_all/bn_all-1.0

        agg.append({"c": cid, "e20_dev": ce20, "e20_all": ce20_all, "dd": dd})

    agg.sort(key=lambda r: r["e20_dev"], reverse=True)
    bl = next((r for r in agg if r["c"] == "r70_v13_baseline"), None)
    bdd = bl["dd"] if bl else -0.30
    print(f"\nBYD R71-80 (dev 2024-2025):")
    for r in agg:
        print(f"  {r['c']:<30s} e20_dev={r['e20_dev']:.4f} e20_all={r['e20_all']:.4f} dd={r['dd']:.4f}")

    # Also show full period including 2022-2023
    print(f"\nFull period (2022H2-2025H2):")
    for r in sorted(agg, key=lambda r: r["e20_all"], reverse=True)[:10]:
        print(f"  {r['c']:<30s} e20_all={r['e20_all']:.4f} dd={r['dd']:.4f}")

    return agg


# ============================================================
# CNx R41-50: build on r27_all4_cap4
# ============================================================
def cnx_rounds():
    from src.data.foundation import DataFoundation
    from src.research.daily_ranker import prepare_ranker_frame
    from src.research.rolling_windows import purge_training_tail
    from src.research.universe_robustness import validate_no_nan_inputs
    from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

    RET = "Ref($close, -10) / $close - 1"
    WINS = ("2024H1", "2024H2", "2025H1", "2025H2")
    TRAIN = {"2024H1": ("2021-01-01", "2023-12-31"), "2024H2": ("2021-01-01", "2024-06-30"),
             "2025H1": ("2021-01-01", "2024-12-31"), "2025H2": ("2021-01-01", "2025-06-30")}

    ALL4 = ["cn_balanced_ohlcv", "cn_volatility_reversal", "cn_price_volume_pressure", "cn_short_reversal_liquidity"]

    configs = [
        ("r41_all4_deeper", ALL4, {"n_gain_bins":7,"num_boost_round":300,"max_leaves":63,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 15, 4),
        ("r42_all4_gain9", ALL4, {"n_gain_bins":9,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 15, 4),
        ("r43_all4_reg", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.1,"reg_lambda":2.0,"seed":42}, 15, 4),
        ("r44_all4_top18_cap4", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 18, 4),
        ("r45_all4_top12_cap4", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 12, 4),
        ("r46_all4_cap5", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 15, 5),
        ("r47_all4_cap3", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 15, 3),
        ("r48_all4_200r_lr05", ALL4, {"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 15, 4),
        ("r49_all4_top20_cap5", ALL4, {"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"seed":42}, 20, 5),
        ("r50_baseline", ["cn_balanced_ohlcv"], {"n_gain_bins":5,"num_boost_round":100,"max_leaves":31,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"seed":42}, 15, None),
    ]

    foundation = DataFoundation(market="cn", benchmark="000300", provider_uri="data/providers/cn",
                                 factor_library_path="configs/factor_libraries/ohlcv.yaml",
                                 universe_config_path="configs/research_universes/cn_selected_equities_v3.yaml",
                                 sector_config_path="configs/research_classifications/cn130_sector_industry_v1.yaml")
    foundation.initialize()
    smap = foundation.sector_map

    config_exprs = {}
    for cid, groups, _, _, _ in configs:
        config_exprs[cid] = foundation.factor_expressions(list(groups))
    all_e = set(); [all_e.update(v) for v in config_exprs.values()]
    all_exprs = sorted(all_e); e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[cnx] {len(all_exprs)} expressions")

    def select_strict(scores, sm, tn, mps):
        if mps is None: return list(scores.nlargest(tn).index)
        ranked = scores.sort_values(ascending=False)
        sel, cnt = [], {}
        for sym, _ in ranked.items():
            s = str(sym); sec = sm.get(s, "Unknown")
            if cnt.get(sec, 0) >= mps: continue
            sel.append(s); cnt[sec] = cnt.get(sec, 0) + 1
            if len(sel) >= tn: break
        return sel

    all_r = []
    for win in WINS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        f, ret, bm, ed = wdata["features"], wdata["returns"], wdata["benchmark"], wdata["eval_dates"]
        d = f.index.get_level_values("datetime")
        tm = (d >= pd.Timestamp(ts)) & (d <= pd.Timestamp(te))
        testm = d.isin(ed)

        for cid, groups, cal_d, tn, mps in configs:
            ei = [e2i[e] for e in config_exprs[cid]]
            cf = f.iloc[:, ei].copy(); cf.columns = [f"f{i}" for i in range(len(ei))]
            cft = cf.loc[tm].copy(); rt = ret.loc[tm].copy()
            cft, rt = purge_training_tail(cft, rt, holding_days=10)
            v, _ = validate_no_nan_inputs(cft, context=f"{win}/{cid}")
            if not v: continue
            dc = {"n_gain_bins":5,"num_boost_round":100,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}
            cal = XGBNativeCalibration.from_dict({**dc, **cal_d})
            xr, yr, gr = prepare_ranker_frame(cft, rt)
            fitted = fit_xgb_native_daily_ranker(xr, yr, gr, calibration=cal)
            cfe = cf.loc[testm].copy(); scores = predict_xgb_native_daily_ranker(fitted, cfe)
            rte = ret.loc[testm].copy()

            for cost in (20, 60):
                rd = [ed[i] for i in range(0, len(ed), 10)]
                pr, pw = [], None
                for dt in rd:
                    try:
                        ds = scores.xs(dt, level="datetime"); dr = rte.xs(dt, level="datetime")
                    except KeyError: continue
                    sel = select_strict(ds["score"], smap, tn, mps)
                    sel = [s for s in sel if s in dr.index]
                    if not sel: continue
                    n = len(sel); cw = {s: 1.0/n for s in sel}
                    if pw is not None:
                        alls = set(list(pw) + list(cw))
                        to = sum(abs(cw.get(s, 0) - pw.get(s, 0)) for s in alls)
                    else: to = 1.0
                    pr.append(float(dr.loc[sel, "return"].mean()) - to * cost / 10000.0)
                    pw = cw
                if not pr: continue
                ps = pd.Series(pr, index=pd.DatetimeIndex([rd[i] for i in range(len(pr))]))
                cm = ps.index.intersection(bm.index)
                if len(cm) == 0: continue
                pa = ps[cm]; ba = bm.loc[cm, "return"]
                sc = float(np.prod(1.0+pa)-1.0); bc = float(np.prod(1.0+ba)-1.0)
                dd = float(((1.0+pa).cumprod()/(1.0+pa).cumprod().cummax()-1.0).min())
                re = (1.0+sc)/(1.0+bc)-1.0 if bc>-1 else 0.0
                all_r.append({"c": cid, "w": win, "cost": cost, "re": re, "dd": dd, "sc": sc, "bc": bc})

    byc = defaultdict(lambda: {"w20": {}, "w60": {}})
    for r in all_r:
        k = "w20" if r["cost"] == 20 else "w60"; byc[r["c"]][k][r["w"]] = r
    agg = []
    for cid, cd in byc.items():
        if len(cd["w20"]) != 4: continue
        o20 = [cd["w20"][w] for w in WINS]
        sn = math.prod(1.0+r["sc"] for r in o20); bn = math.prod(1.0+r["bc"] for r in o20)
        ce20 = sn/bn-1.0; dd = min(r["dd"] for r in o20)
        pos = sum(1 for r in o20 if r["re"] > 0)
        ss = max(r["re"] for r in o20)/sum(r["re"] for r in o20 if r["re"]>0) if sum(r["re"] for r in o20 if r["re"]>0)>0 else 1.0
        ce60 = None
        if len(cd["w60"]) == 4:
            o60 = [cd["w60"][w] for w in WINS]
            ce60 = math.prod(1.0+r["sc"] for r in o60)/math.prod(1.0+r["bc"] for r in o60)-1.0
        agg.append({"c": cid, "e20": ce20, "e60": ce60, "dd": dd, "pos": pos, "share": ss})

    agg.sort(key=lambda r: r["e20"], reverse=True)
    bl = next((r for r in agg if r["c"] == "r50_baseline"), None)
    bdd = bl["dd"] if bl else -0.20; bex = bl["e20"] if bl else 0.0
    print(f"\nCNx Baseline: DD={bdd:.4f} Exc={bex:.4f}")
    for r in agg:
        e60s = f'{r["e60"]:.4f}' if r["e60"] else 'N/A'
        ddg = r["dd"] >= bdd + 0.03 or r["dd"] >= -0.22
        eg = r["e20"] >= 0.90 * bex; e60g = r["e60"] is not None and r["e60"] > 0
        sg = r["share"] < 0.55; pg = r["pos"] == 4
        ap = ddg and eg and e60g and sg and pg
        print(f'{"PASS" if ap else "FAIL":>5s} {r["c"]:<30s} e20={r["e20"]:.4f} dd={r["dd"]:.4f} e60={e60s} share={r["share"]:.4f}')

    return agg


# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("USx R41-50")
    print("=" * 60)
    usx_rounds()

    print("\n" + "=" * 60)
    print("CNx R41-50")
    print("=" * 60)
    cnx_rounds()

    print("\n" + "=" * 60)
    print("QQQR R41-50")
    print("=" * 60)
    qqqr_rounds()

    print("\n" + "=" * 60)
    print("BYD R71-80")
    print("=" * 60)
    byd_rounds()
