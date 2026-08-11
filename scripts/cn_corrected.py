"""Corrected CNx optimization — aligned with #770 methodology.

Fixes:
- Turnover-based cost: actual weight_changes × cost_bps, not flat discount
- Sector cap: strict, no fallback fill
- Proper baseline comparison against uncapped CN x1.0
- 2024H1-2025H2 selection only, 2026H1 reporting
"""
from __future__ import annotations

import json, math, sys
from collections import defaultdict
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

# ===== Configurations to test =====
CN_CONFIGS = [
    # (cid, factor_groups, cal_dict, top_n, max_per_sector)
    # Baseline: CN x1.0 equivalent (no sector cap)
    ("cn_baseline", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 1.0, "colsample_bytree": 1.0, "seed": 42}, 15, None),

    # r11_sampled equivalent (USx winner)
    ("cn_sampled_cap4", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 200, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),

    # Lower LR variant
    ("cn_lowerlr_cap4", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),

    # With pressure factors
    ("cn_pressure_cap4", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     {"n_gain_bins": 5, "num_boost_round": 200, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),

    # Tighter cap
    ("cn_sampled_cap3", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 200, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 3),

    # Fewer stocks
    ("cn_sampled_top12_cap4", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 200, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 12, 4),
]


def select_sector_capped_strict(scores, sector_map, top_n, max_per_sector):
    """STRICT sector cap: if insufficient qualified stocks, return only available — no fallback fill."""
    ranked = scores.sort_values(ascending=False)
    selected, counts = [], {}
    for sym, _ in ranked.items():
        sym_str = str(sym)
        sec = sector_map.get(sym_str, "Unknown")
        if counts.get(sec, 0) >= max_per_sector:
            continue
        selected.append(sym_str)
        counts[sec] = counts.get(sec, 0) + 1
        if len(selected) >= top_n:
            break
    return selected  # May be fewer than top_n — that's the correct behavior


def run():
    foundation = DataFoundation(market="cn", benchmark="000300", provider_uri="data/providers/cn",
                                 factor_library_path="configs/factor_libraries/ohlcv.yaml",
                                 universe_config_path="configs/research_universes/cn_selected_equities_v3.yaml",
                                 sector_config_path="configs/research_classifications/cn130_sector_industry_v1.yaml")
    foundation.initialize()
    sector_map = foundation.sector_map
    symbols = foundation.symbols
    print(f"[cn] {len(symbols)} symbols, {len(sector_map)} sectors")

    # Precompute factor expressions
    config_exprs = {}
    for cid, groups, _, _, _ in CN_CONFIGS:
        config_exprs[cid] = foundation.factor_expressions(list(groups))
    all_exprs_set = set()
    for e in config_exprs.values():
        all_exprs_set.update(e)
    all_exprs = sorted(all_exprs_set)
    e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[cn] {len(all_exprs)} total unique expressions")

    all_results = []
    for win in WINDOWS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        features = wdata["features"]
        returns = wdata["returns"]
        benchmark = wdata["benchmark"]
        eval_dates = wdata["eval_dates"]

        dates = features.index.get_level_values("datetime")
        tm = (dates >= pd.Timestamp(ts)) & (dates <= pd.Timestamp(te))
        testm = dates.isin(eval_dates)

        for cid, groups, cal_dict, top_n, mps in CN_CONFIGS:
            ei = [e2i[e] for e in config_exprs[cid]]
            nf = len(ei)

            cf_all = features.iloc[:, ei].copy()
            cf_all.columns = [f"f{i}" for i in range(nf)]
            cf_train = cf_all.loc[tm].copy()
            ret_train = returns.loc[tm].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{win}/{cid}")
            if not valid:
                continue

            default_cal = {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "max_depth": 0,
                           "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 1.0,
                           "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
            cal = XGBNativeCalibration.from_dict({**default_cal, **cal_dict})
            xr, yr, gr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(xr, yr, gr, calibration=cal)
            cf_test = cf_all.loc[testm].copy()
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)
            ret_test = returns.loc[testm].copy()

            # Evaluate at 20 and 60 bps with PROPER turnover-based cost
            for cost_bps in (20, 60):
                cadence = 10
                rd = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
                port_rets, turnovers = [], []
                prev_weights = None

                for d in rd:
                    try:
                        ds = scores.xs(d, level="datetime")
                        dr = ret_test.xs(d, level="datetime")
                    except KeyError:
                        continue

                    ss = ds["score"]
                    if mps and sector_map:
                        selected = select_sector_capped_strict(ss, sector_map, top_n, mps)
                    else:
                        selected = list(ss.nlargest(top_n).index)

                    selected = [s for s in selected if s in dr.index]
                    if not selected:
                        continue
                    n_sel = len(selected)
                    current_weights = {s: 1.0 / n_sel for s in selected}

                    # Compute turnover vs previous weights
                    if prev_weights is not None:
                        all_syms = set(list(prev_weights.keys()) + list(current_weights.keys()))
                        turnover = sum(abs(current_weights.get(s, 0) - prev_weights.get(s, 0)) for s in all_syms)
                    else:
                        turnover = 1.0  # Initial entry

                    # Gross return — average of selected stock returns
                    sel_returns = dr.loc[selected, "return"]
                    gross_ret = float(sel_returns.mean())

                    # Net return = gross - cost
                    cost = turnover * cost_bps / 10000.0
                    net_ret = gross_ret - cost

                    port_rets.append(net_ret)
                    turnovers.append(float(turnover))
                    prev_weights = current_weights

                if not port_rets:
                    continue

                prs = pd.Series(port_rets, index=pd.DatetimeIndex([rd[i] for i in range(len(port_rets))]))
                common = prs.index.intersection(benchmark.index)
                if len(common) == 0:
                    continue
                pa = prs[common]
                ba = benchmark.loc[common, "return"]

                sc = float(np.prod(1.0 + pa) - 1.0)
                bc = float(np.prod(1.0 + ba) - 1.0)
                cum = (1.0 + pa).cumprod()
                dd = float(((cum - cum.cummax()) / cum.cummax()).min())
                re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0

                all_results.append({
                    "config": cid, "window": win, "cost_bps": cost_bps,
                    "relative_excess": re, "max_drawdown": dd,
                    "strategy_compound": sc, "benchmark_compound": bc,
                    "n_periods": len(pa), "avg_turnover": float(np.mean(turnovers)),
                })

        # Show top-3 for this window
        w20 = [r for r in all_results if r["window"] == win and r["cost_bps"] == 20]
        w20.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"[{win}] top-3: " + " | ".join(
            f"{r['config']}: exc={r['relative_excess']:.3f} dd={r['max_drawdown']:.3f} to={r['avg_turnover']:.2f}"
            for r in w20[:3]
        ))

    # Cross-window aggregation
    by_c = defaultdict(lambda: {"w20": {}, "w60": {}})
    for r in all_results:
        k = "w20" if r["cost_bps"] == 20 else "w60"
        by_c[r["config"]][k][r["window"]] = r

    agg = []
    for cid, data in by_c.items():
        if len(data["w20"]) != 4:
            continue
        o20 = [data["w20"][w] for w in WINDOWS]
        sn = math.prod(1.0 + r["strategy_compound"] for r in o20)
        bn = math.prod(1.0 + r["benchmark_compound"] for r in o20)
        ce20 = sn / bn - 1.0
        dd = min(r["max_drawdown"] for r in o20)
        pos = sum(1 for r in o20 if r["relative_excess"] > 0)
        strongest = max(r["relative_excess"] for r in o20) / sum(
            r["relative_excess"] for r in o20 if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in o20 if r["relative_excess"] > 0) > 0 else 1.0
        avg_to = float(np.mean([r["avg_turnover"] for r in o20]))

        ce60 = None
        if len(data["w60"]) == 4:
            o60 = [data["w60"][w] for w in WINDOWS]
            ce60 = math.prod(1.0 + r["strategy_compound"] for r in o60) / math.prod(
                1.0 + r["benchmark_compound"] for r in o60) - 1.0

        agg.append({"config": cid, "exc20": ce20, "exc60": ce60, "dd": dd, "pos": pos,
                     "strongest": strongest, "avg_turnover": avg_to,
                     "pw": {r["window"]: {"exc": r["relative_excess"], "dd": r["max_drawdown"]} for r in o20}})

    agg.sort(key=lambda r: r["exc20"], reverse=True)

    # Gate analysis vs baseline
    bl = next((r for r in agg if r["config"] == "cn_baseline"), None)
    if bl:
        base_dd = bl["dd"]
        base_exc = bl["exc20"]
        print(f"\nBaseline (cn_baseline): DD={base_dd:.4f}, Exc@20={base_exc:.4f}")
    else:
        base_dd, base_exc = -0.40, 0.0

    print(f"\n{'Config':<30s} {'Exc@20':>8s} {'DD':>8s} {'Exc@60':>8s} {'DD_Impr':>8s} {'Pos':>4s} {'Share':>7s} {'Turn':>7s}")
    print("-" * 100)
    for r in agg:
        exc60s = f'{r["exc60"]:.4f}' if r["exc60"] else 'N/A'
        dd_impr = base_dd - r["dd"] if bl else 0
        # Gate check
        dd_gate = r["dd"] >= base_dd + 0.03 or r["dd"] >= -0.22
        exc_gate = r["exc20"] >= 0.90 * base_exc
        exc60_gate = r["exc60"] is not None and r["exc60"] > 0
        share_gate = r["strongest"] < 0.55
        pos_gate = r["pos"] == 4
        all_pass = dd_gate and exc_gate and exc60_gate and share_gate and pos_gate
        status = "PASS" if all_pass else "FAIL"
        print(f'{status:<5s} {r["config"]:<30s} {r["exc20"]:>8.4f} {r["dd"]:>8.4f} {exc60s:>8s} {dd_impr:>8.4f} {r["pos"]:>4} {r["strongest"]:>7.4f} {r["avg_turnover"]:>7.2f}')

    # Save
    out = Path("artifacts/optimization/cn_corrected_v1/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"baseline_dd": base_dd, "baseline_exc": base_exc, "results": agg}, indent=2, default=str))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    run()
