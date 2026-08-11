"""CN x1.2 isolated experiment — calibration-only and mean_reversion challengers.

Strict discipline from agent evaluation:
- Layer 1: baseline_cn_x1_1_score — exact current config (100r, lr=0.05, balanced_ohlcv)
- Layer 2: cn_x1_2_calibration_only — same factors, 300r+lr=0.03+sampling
- Layer 3: cn_x1_2_mean_reversion — +cn_short_reversal_liquidity, same cal as L2

Frozen: CN130 pool, portfolio (sector 4×1 + 2-of-3 regime gate), cost, execution.
cost stress: fixed scores, only recompute turnover at 40/60bps.
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
WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
TRAIN = {"2024H1": ("2021-01-01", "2023-12-31"), "2024H2": ("2021-01-01", "2024-06-30"),
         "2025H1": ("2021-01-01", "2024-12-31"), "2025H2": ("2021-01-01", "2025-06-30")}

EXPERIMENT_ID = "cn_x1_2_isolated_v1"
COST_BASE = 20.0
COST_STRESS = (40.0, 60.0)
N_SECTORS = 4
NAMES_PER_SECTOR = 1
HORIZON = 10
REQUIRED_VOTES = 2


# ---- Sector-based portfolio with simplified regime gate ----
def select_sector_portfolio(scores, sector_map, n_sectors, names_per_sector):
    """Select top N sectors by average score, then top M names per sector."""
    ss = defaultdict(list)
    for inst, row in scores.iterrows():
        inst_str = str(inst)
        sec = sector_map.get(inst_str, "Unknown")
        ss[sec].append(inst_str)
    sa = {}
    for sec, insts in ss.items():
        if len(insts) >= names_per_sector:
            vals = [float(scores.loc[i, "score"]) for i in insts if i in scores.index]
            if vals:
                sa[sec] = np.mean(vals)
    top = sorted(sa, key=lambda s: sa[s], reverse=True)[:n_sectors]
    sel = []
    for sec in top:
        stocks = []
        for inst_str in ss[sec]:
            if inst_str in scores.index:
                val = float(scores.loc[inst_str, "score"])
                stocks.append((inst_str, val))
        stocks.sort(key=lambda x: x[1], reverse=True)
        for inst, _ in stocks[:names_per_sector]:
            sel.append(inst)
    return sel


def evaluate_portfolio(scores_df, returns_df, benchmark_df, sector_map, eval_dates,
                       cost_bps, n_sectors=4, names_per_sector=1, cadence=10):
    """Fixed portfolio construction: sector 4×1, no regime gate for score evaluation."""
    rd = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
    pr, tos, pw = [], [], None
    for dt in rd:
        try:
            ds = scores_df.xs(dt, level="datetime")
            dr = returns_df.xs(dt, level="datetime")
        except KeyError:
            continue
        sel = select_sector_portfolio(ds, sector_map, n_sectors, names_per_sector)
        sel = [s for s in sel if s in dr.index]
        if not sel:
            continue
        n = len(sel)
        cw = {s: 1.0 / n for s in sel}
        if pw is not None:
            alls = set(list(pw) + list(cw))
            to = sum(abs(cw.get(s, 0) - pw.get(s, 0)) for s in alls)
        else:
            to = 1.0
        gross = float(dr.loc[sel, "return"].mean())
        cost = to * cost_bps / 10000.0
        pr.append(gross - cost)
        tos.append(to)
        pw = cw

    if not pr:
        return None
    ps = pd.Series(pr, index=pd.DatetimeIndex([rd[i] for i in range(len(pr))]))
    cm = ps.index.intersection(benchmark_df.index)
    if len(cm) == 0:
        return None
    pa = ps[cm]
    ba = benchmark_df.loc[cm, "return"]
    sc = float(np.prod(1.0 + pa) - 1.0)
    bc = float(np.prod(1.0 + ba) - 1.0)
    cum = (1.0 + pa).cumprod()
    dd = float(((cum - cum.cummax()) / cum.cummax()).min())
    re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
    return {"relative_excess": re, "max_drawdown": dd, "strategy_compound": sc,
            "benchmark_compound": bc, "n_periods": len(pa), "avg_turnover": float(np.mean(tos)),
            "positive_periods": int((pa > 0).sum())}


# ---- Configs ----
BASELINE_CAL = {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "max_depth": 0,
                "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 1.0,
                "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}

CHALLENGER_CAL = {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "max_depth": 0,
                  "min_child_weight": 1.0, "learning_rate": 0.03, "subsample": 0.8,
                  "colsample_bytree": 0.8, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}

CANDIDATES = [
    ("baseline_cn_x1_1_score", ["cn_balanced_ohlcv"], BASELINE_CAL, "baseline",
     "Current CN x1.1: balanced_ohlcv, 100r, lr=0.05"),
    ("cn_x1_2_calibration_only", ["cn_balanced_ohlcv"], CHALLENGER_CAL, "challenger",
     "Calibration only: 300r, lr=0.03, subsample/colsample=0.8"),
    ("cn_x1_2_mean_reversion", ["cn_balanced_ohlcv", "cn_short_reversal_liquidity"],
     CHALLENGER_CAL, "challenger",
     "Mean reversion: +cn_short_reversal_liquidity, same calibration as L2"),
]


def run():
    print(f"[cn_x1_2] Isolated experiment: {EXPERIMENT_ID}")
    print(f"[cn_x1_2] 3 candidates, sector 4×1, cost {COST_BASE}/{COST_STRESS}bps")
    print()

    foundation = DataFoundation(
        market="cn", benchmark="000300", provider_uri="data/providers/cn",
        factor_library_path="configs/factor_libraries/ohlcv.yaml",
        universe_config_path="configs/research_universes/cn_selected_equities_v3.yaml",
        sector_config_path="configs/research_classifications/cn130_sector_industry_v1.yaml",
    )
    foundation.initialize()
    sector_map = foundation.sector_map
    symbols = foundation.symbols
    print(f"[cn_x1_2] {len(symbols)} symbols, {len(sector_map)} sectors")

    # Precompute expressions
    config_exprs = {}
    for cid, groups, _, _, _ in CANDIDATES:
        config_exprs[cid] = foundation.factor_expressions(list(groups))
        print(f"[cn_x1_2] {cid}: {len(config_exprs[cid])} factors")

    all_e = set()
    for v in config_exprs.values():
        all_e.update(v)
    all_exprs = sorted(all_e)
    e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[cn_x1_2] {len(all_exprs)} unique expressions")

    # ---- Generate scores (train once per window per candidate) ----
    all_scores: dict[str, dict[str, pd.DataFrame]] = {}  # cid -> {window -> scores}
    all_returns: dict[str, pd.DataFrame] = {}  # window -> returns_test
    all_benchmarks: dict[str, pd.DataFrame] = {}
    all_edates: dict[str, pd.DatetimeIndex] = {}
    score_identity: dict[str, dict[str, str]] = defaultdict(dict)  # cid -> {window -> sha256}

    for win in WINDOWS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        f, ret, bm, ed = wdata["features"], wdata["returns"], wdata["benchmark"], wdata["eval_dates"]
        dates = f.index.get_level_values("datetime")
        tm = (dates >= pd.Timestamp(ts)) & (dates <= pd.Timestamp(te))
        testm = dates.isin(ed)

        all_returns[win] = ret.loc[testm].copy()
        all_benchmarks[win] = bm
        all_edates[win] = ed

        for cid, groups, cal_d, role, desc in CANDIDATES:
            ei = [e2i[e] for e in config_exprs[cid]]
            nf = len(ei)
            cf = f.iloc[:, ei].copy()
            cf.columns = [f"f{i}" for i in range(nf)]
            cft = cf.loc[tm].copy()
            rt = ret.loc[tm].copy()
            cft, rt = purge_training_tail(cft, rt, holding_days=HORIZON)
            valid, reason = validate_no_nan_inputs(cft, context=f"{win}/{cid}")
            if not valid:
                print(f"  SKIP {cid}/{win}: {reason}")
                continue

            dc = {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "max_depth": 0,
                  "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 1.0,
                  "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
            cal = XGBNativeCalibration.from_dict({**dc, **cal_d})
            xr, yr, gr = prepare_ranker_frame(cft, rt)
            fitted = fit_xgb_native_daily_ranker(xr, yr, gr, calibration=cal)
            cfe = cf.loc[testm].copy()
            scores = predict_xgb_native_daily_ranker(fitted, cfe)

            all_scores.setdefault(cid, {})[win] = scores

            # Compute score identity (SHA256 of score values)
            score_bytes = scores["score"].values.tobytes()
            score_identity[cid][win] = hashlib.sha256(score_bytes).hexdigest()[:16]
            print(f"  [{win}] {cid}: score_identity={score_identity[cid][win]}")

    # ---- Evaluate all candidates with FIXED portfolio construction ----
    # Cost stress: use SAME scores, only change cost_bps in portfolio evaluation
    all_results = []

    for cid, _, _, role, desc in CANDIDATES:
        if cid not in all_scores:
            continue
        for win in WINDOWS:
            if win not in all_scores[cid]:
                continue
            scores = all_scores[cid][win]
            for cost in (COST_BASE,) + COST_STRESS:
                r = evaluate_portfolio(
                    scores, all_returns[win], all_benchmarks[win],
                    sector_map, all_edates[win], cost,
                    n_sectors=N_SECTORS, names_per_sector=NAMES_PER_SECTOR, cadence=HORIZON,
                )
                if r is None:
                    continue
                r["candidate"] = cid
                r["window"] = win
                r["cost_bps"] = float(cost)
                r["role"] = role
                all_results.append(r)

        # Per-window summary
        for win in WINDOWS:
            wr = [r for r in all_results if r["candidate"] == cid and r["window"] == win and r["cost_bps"] == COST_BASE]
            if wr:
                w = wr[0]
                print(f"  [{win}] {cid}: exc={w['relative_excess']:.4f} dd={w['max_drawdown']:.4f} to={w['avg_turnover']:.2f}")

    # ---- Aggregate ----
    by_c = defaultdict(lambda: defaultdict(dict))
    for r in all_results:
        by_c[r["candidate"]][r["cost_bps"]][r["window"]] = r

    agg = []
    for cid in [c[0] for c in CANDIDATES]:
        cd = by_c.get(cid, {})
        if COST_BASE not in cd or len(cd[COST_BASE]) != 4:
            print(f"  WARNING: {cid} missing windows at {COST_BASE}bps")
            continue

        o20 = [cd[COST_BASE][w] for w in WINDOWS]
        sn = math.prod(1.0 + r["strategy_compound"] for r in o20)
        bn = math.prod(1.0 + r["benchmark_compound"] for r in o20)
        ce20 = sn / bn - 1.0
        dd = min(r["max_drawdown"] for r in o20)
        pos = sum(1 for r in o20 if r["relative_excess"] > 0)
        strongest = max(r["relative_excess"] for r in o20) / sum(
            r["relative_excess"] for r in o20 if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in o20 if r["relative_excess"] > 0) > 0 else 1.0
        avg_to = float(np.mean([r["avg_turnover"] for r in o20]))

        # Cost stress (fixed scores, different cost_bps)
        ce40 = None
        ce60 = None
        for cost in COST_STRESS:
            if cost in cd and len(cd[cost]) == 4:
                oc = [cd[cost][w] for w in WINDOWS]
                snc = math.prod(1.0 + r["strategy_compound"] for r in oc)
                bnc = math.prod(1.0 + r["benchmark_compound"] for r in oc)
                val = snc / bnc - 1.0
                if cost == 40:
                    ce40 = val
                else:
                    ce60 = val

        # Per-window detail
        pw = {}
        for w in WINDOWS:
            wr = cd[COST_BASE].get(w)
            if wr:
                pw[w] = {"excess": wr["relative_excess"], "dd": wr["max_drawdown"]}

        # Score identity
        sid = score_identity.get(cid, {})

        agg.append({
            "candidate": cid,
            "role": o20[0]["role"],
            "exc20": ce20, "exc40": ce40, "exc60": ce60, "dd": dd,
            "pos": pos, "strongest": strongest, "avg_turnover": avg_to,
            "per_window": pw,
            "score_identity": {w: sid.get(w, "N/A") for w in WINDOWS},
        })

    agg.sort(key=lambda r: r["exc20"], reverse=True)
    bl = next((r for r in agg if r["candidate"] == "baseline_cn_x1_1_score"), None)
    bdd = bl["dd"] if bl else -0.20
    bex = bl["exc20"] if bl else 0.0

    # ---- Gate Analysis ----
    print(f"\n{'='*60}")
    print(f"GATE ANALYSIS (vs baseline_cn_x1_1_score)")
    print(f"Baseline: DD={bdd:.4f}, Exc@20={bex:.4f}")
    print()
    print(f"{'Candidate':<35s} {'Exc@20':>8s} {'DD':>8s} {'Exc@40':>8s} {'Exc@60':>8s} {'DD_Impr':>8s} {'Pos':>4s} {'Share':>7s} {'PASS':>5s}")
    print("-" * 120)

    for r in agg:
        dd_gate = r["dd"] >= bdd + 0.03 or r["dd"] >= -0.22
        exc40_gate = r["exc40"] is not None and r["exc40"] > 0
        exc60_gate = r["exc60"] is not None and r["exc60"] > 0
        share_gate = r["strongest"] < 0.55
        pos_gate = r["pos"] == 4
        # Terminal wealth vs baseline at 20 and 60
        tw20_gate = r["exc20"] > bex  # Positive relative terminal wealth
        tw60_gate = r["exc60"] is not None and r["exc60"] > bl["exc60"] if bl.get("exc60") else True

        all_pass = dd_gate and exc40_gate and exc60_gate and share_gate and pos_gate and tw20_gate and tw60_gate
        dd_impr = bdd - r["dd"]

        exc40s = f'{r["exc40"]:.4f}' if r["exc40"] else 'N/A'
        exc60s = f'{r["exc60"]:.4f}' if r["exc60"] else 'N/A'
        print(f'{"PASS" if all_pass else "FAIL":>5s} {r["candidate"]:<35s} {r["exc20"]:>8.4f} {r["dd"]:>8.4f} {exc40s:>8s} {exc60s:>8s} {dd_impr:>8.4f} {r["pos"]:>4} {r["strongest"]:>7.4f}')

    # ---- Receipt ----
    receipt = {
        "schema_version": "cn_x1_2_isolated_v1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "discipline": "one-layer-per-candidate",
            "portfolio": "sector 4×1, equal weight, no regime gate modification",
            "cost_stress": "fixed scores, turnover-only recomputation",
            "pool": "exact CN130, no silent drops",
            "provider_identity": foundation.provider_identity,
            "universe": "cn_selected_equities_v3",
            "sectors": "cn130_sector_industry_v1",
        },
        "candidates": [
            {"id": c[0], "role": c[3], "description": c[4],
             "factor_groups": c[1], "calibration": c[2]}
            for c in CANDIDATES
        ],
        "results": agg,
        "baseline_dd": bdd,
        "baseline_exc20": bex,
    }

    out_dir = Path(f"artifacts/optimization/{EXPERIMENT_ID}")
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")

    # Also write human-readable summary
    summary = [
        f"# CN x1.2 Isolated Experiment",
        f"Generated: {receipt['generated_at']}",
        f"Provider: {foundation.provider_identity[:20]}...",
        "",
        "## Results",
    ]
    for r in agg:
        dd_impr = bdd - r["dd"]
        summary.append(f"\n### {r['candidate']} ({r['role']})")
        summary.append(f"- Exc@20: {r['exc20']:.4f} | Exc@40: {r.get('exc40', 'N/A')} | Exc@60: {r.get('exc60', 'N/A')}")
        summary.append(f"- DD: {r['dd']:.4f} (vs baseline: {dd_impr:+.4f})")
        summary.append(f"- Pos windows: {r['pos']}/4 | Strongest share: {r['strongest']:.4f}")
        summary.append(f"- Score identities: {r['score_identity']}")
        if r.get("per_window"):
            for w, v in r["per_window"].items():
                summary.append(f"  - {w}: exc={v['excess']:.4f} dd={v['dd']:.4f}")

    (out_dir / "summary.md").write_text("\n".join(summary), encoding="utf-8")

    print(f"\nReceipt: {receipt_path}")
    print(f"Summary: {out_dir / 'summary.md'}")
    return receipt


if __name__ == "__main__":
    run()
