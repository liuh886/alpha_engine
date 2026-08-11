"""CNx R21-40: target concentration gate blocker + factor group optimization.

Corrected methodology from #770: strict sector cap, turnover-based cost, uncapped baseline comparison.

Gate blocker for cn_lowerlr_cap4: strongest_share=0.5558 > 0.55
Strategy: test configurations that reduce window concentration while maintaining excess.
"""
from __future__ import annotations

import json, math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.foundation import DataFoundation
from src.research.daily_ranker import prepare_ranker_frame
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

RET = "Ref($close, -10) / $close - 1"
WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
TRAIN = {"2024H1": ("2021-01-01", "2023-12-31"), "2024H2": ("2021-01-01", "2024-06-30"),
         "2025H1": ("2021-01-01", "2024-12-31"), "2025H2": ("2021-01-01", "2025-06-30")}

# R21-40 configs targeting the concentration gate
CONFIGS = [
    # R21-24: Tighter sector cap + more stocks → more diversified
    ("r21_top20_cap4", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 20, 4),
    ("r22_top15_cap3", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 3),
    ("r23_top12_cap4", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 12, 4),

    # R24-27: Pressure + reversal factors → diversify signal sources
    ("r24_pressure_cap4", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),
    ("r25_volrev_cap4", ["cn_balanced_ohlcv", "cn_volatility_reversal"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),
    ("r26_revliq_cap4", ["cn_balanced_ohlcv", "cn_short_reversal_liquidity"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),
    ("r27_all4_cap4", ["cn_balanced_ohlcv", "cn_volatility_reversal", "cn_price_volume_pressure", "cn_short_reversal_liquidity"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),

    # R28-31: Calibration variants with lower_lr
    ("r28_deeper_lr", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 7, "num_boost_round": 300, "max_leaves": 63, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),
    ("r29_regularized", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "reg_alpha": 0.1, "reg_lambda": 2.0, "seed": 42}, 15, 4),
    ("r30_gain9", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 9, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),
    ("r31_sampled_cap4_200r", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 200, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 4),

    # R32-35: Diversification-focused combos
    ("r32_top20_cap5", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 20, 5),
    ("r33_top15_cap5", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 5),
    ("r34_top18_cap3", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 18, 3),

    # R35-38: Pressure factor + diversification
    ("r35_pressure_top20_cap4", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 20, 4),
    ("r36_pressure_top15_cap5", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 15, 5),

    # R37-40: Baseline reference + best guess combos
    ("r37_baseline_100r", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "learning_rate": 0.05,
      "subsample": 1.0, "colsample_bytree": 1.0, "seed": 42}, 15, None),
    ("r38_best_diversified", ["cn_balanced_ohlcv", "cn_volatility_reversal"],
     {"n_gain_bins": 7, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 18, 5),
    ("r39_best_concentrated", ["cn_balanced_ohlcv"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 12, 3),
    ("r40_all4_top20_cap5", ["cn_balanced_ohlcv", "cn_volatility_reversal", "cn_price_volume_pressure", "cn_short_reversal_liquidity"],
     {"n_gain_bins": 5, "num_boost_round": 300, "max_leaves": 31, "learning_rate": 0.03,
      "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}, 20, 5),
]


def select_strict(scores, sector_map, top_n, max_per_sector):
    if max_per_sector is None:
        return list(scores.nlargest(top_n).index)
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
    return selected


def run():
    foundation = DataFoundation(market="cn", benchmark="000300", provider_uri="data/providers/cn",
                                 factor_library_path="configs/factor_libraries/ohlcv.yaml",
                                 universe_config_path="configs/research_universes/cn_selected_equities_v3.yaml",
                                 sector_config_path="configs/research_classifications/cn130_sector_industry_v1.yaml")
    foundation.initialize()
    sector_map = foundation.sector_map

    config_exprs = {}
    for cid, groups, _, _, _ in CONFIGS:
        config_exprs[cid] = foundation.factor_expressions(list(groups))
    all_exprs_set = set()
    for e in config_exprs.values():
        all_exprs_set.update(e)
    all_exprs = sorted(all_exprs_set)
    e2i = {e: i for i, e in enumerate(all_exprs)}
    print(f"[cn] {len(all_exprs)} expressions, {len(CONFIGS)} configs")

    all_results = []
    for win in WINDOWS:
        ts, te = TRAIN[win]
        wdata = foundation.load_window(win, all_exprs)
        features, returns, benchmark, eval_dates = wdata["features"], wdata["returns"], wdata["benchmark"], wdata["eval_dates"]
        dates = features.index.get_level_values("datetime")
        tm = (dates >= pd.Timestamp(ts)) & (dates <= pd.Timestamp(te))
        testm = dates.isin(eval_dates)

        for cid, groups, cal_dict, top_n, mps in CONFIGS:
            ei = [e2i[e] for e in config_exprs[cid]]
            cf_all = features.iloc[:, ei].copy()
            cf_all.columns = [f"f{i}" for i in range(len(ei))]
            cf_train = cf_all.loc[tm].copy()
            ret_train = returns.loc[tm].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, _ = validate_no_nan_inputs(cf_train, context=f"{win}/{cid}")
            if not valid: continue

            dc = {"n_gain_bins": 5, "num_boost_round": 100, "max_leaves": 31, "max_depth": 0,
                  "min_child_weight": 1.0, "learning_rate": 0.05, "subsample": 1.0,
                  "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
            cal = XGBNativeCalibration.from_dict({**dc, **cal_dict})
            xr, yr, gr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(xr, yr, gr, calibration=cal)
            cf_test = cf_all.loc[testm].copy()
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)
            ret_test = returns.loc[testm].copy()

            for cost_bps in (20, 60):
                rd = [eval_dates[i] for i in range(0, len(eval_dates), 10)]
                port_rets, turnovers = [], []
                prev_weights = None
                for d in rd:
                    try:
                        ds = scores.xs(d, level="datetime")
                        dr = ret_test.xs(d, level="datetime")
                    except KeyError: continue
                    selected = select_strict(ds["score"], sector_map, top_n, mps)
                    selected = [s for s in selected if s in dr.index]
                    if not selected: continue
                    n = len(selected)
                    cw = {s: 1.0 / n for s in selected}
                    if prev_weights is not None:
                        all_s = set(list(prev_weights) + list(cw))
                        turnover = sum(abs(cw.get(s, 0) - prev_weights.get(s, 0)) for s in all_s)
                    else:
                        turnover = 1.0
                    gross = float(dr.loc[selected, "return"].mean())
                    cost = turnover * cost_bps / 10000.0
                    port_rets.append(gross - cost)
                    turnovers.append(turnover)
                    prev_weights = cw

                if not port_rets: continue
                prs = pd.Series(port_rets, index=pd.DatetimeIndex([rd[i] for i in range(len(port_rets))]))
                common = prs.index.intersection(benchmark.index)
                if len(common) == 0: continue
                pa = prs[common]
                ba = benchmark.loc[common, "return"]
                sc = float(np.prod(1.0 + pa) - 1.0)
                bc = float(np.prod(1.0 + ba) - 1.0)
                dd = float(((1.0 + pa).cumprod() / (1.0 + pa).cumprod().cummax() - 1.0).min())
                re = (1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0
                all_results.append({"config": cid, "window": win, "cost_bps": cost_bps,
                                     "relative_excess": re, "max_drawdown": dd,
                                     "strategy_compound": sc, "benchmark_compound": bc,
                                     "avg_turnover": float(np.mean(turnovers))})

        w20 = sorted([r for r in all_results if r["window"] == win and r["cost_bps"] == 20],
                     key=lambda r: r["relative_excess"], reverse=True)
        print(f"[{win}] best: {w20[0]['config']} exc={w20[0]['relative_excess']:.4f} dd={w20[0]['max_drawdown']:.4f}")

    # Aggregate
    by_c = defaultdict(lambda: {"w20": {}, "w60": {}})
    for r in all_results:
        k = "w20" if r["cost_bps"] == 20 else "w60"
        by_c[r["config"]][k][r["window"]] = r

    agg = []
    for cid, data in by_c.items():
        if len(data["w20"]) != 4: continue
        o20 = [data["w20"][w] for w in WINDOWS]
        sn = math.prod(1.0 + r["strategy_compound"] for r in o20)
        bn = math.prod(1.0 + r["benchmark_compound"] for r in o20)
        ce20 = sn / bn - 1.0; dd = min(r["max_drawdown"] for r in o20)
        pos = sum(1 for r in o20 if r["relative_excess"] > 0)
        strongest = max(r["relative_excess"] for r in o20) / sum(
            r["relative_excess"] for r in o20 if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in o20 if r["relative_excess"] > 0) > 0 else 1.0
        ce60 = None
        if len(data["w60"]) == 4:
            o60 = [data["w60"][w] for w in WINDOWS]
            ce60 = math.prod(1.0 + r["strategy_compound"] for r in o60) / math.prod(
                1.0 + r["benchmark_compound"] for r in o60) - 1.0
        agg.append({"config": cid, "exc20": ce20, "exc60": ce60, "dd": dd, "pos": pos,
                     "strongest": strongest, "pw": {r["window"]: {"exc": r["relative_excess"], "dd": r["max_drawdown"]} for r in o20}})

    agg.sort(key=lambda r: r["exc20"], reverse=True)
    bl = next((r for r in agg if r["config"] == "r37_baseline_100r"), None)
    base_dd = bl["dd"] if bl else -0.20
    base_exc = bl["exc20"] if bl else 0.0
    print(f"\nBaseline: DD={base_dd:.4f} Exc@20={base_exc:.4f}")
    print(f"\n{'Config':<30s} {'Exc@20':>8s} {'DD':>8s} {'Exc@60':>8s} {'DD_Impr':>8s} {'Pos':>4s} {'Share':>7s} {'Pass':>5s}")
    print("-" * 100)
    for r in agg:
        exc60s = f'{r["exc60"]:.4f}' if r["exc60"] else 'N/A'
        dd_gate = r["dd"] >= base_dd + 0.03 or r["dd"] >= -0.22
        exc_gate = r["exc20"] >= 0.90 * base_exc
        exc60_gate = r["exc60"] is not None and r["exc60"] > 0
        share_gate = r["strongest"] < 0.55
        pos_gate = r["pos"] == 4
        all_pass = dd_gate and exc_gate and exc60_gate and share_gate and pos_gate
        dd_impr = base_dd - r["dd"]
        print(f'{"PASS" if all_pass else "FAIL":>5s} {r["config"]:<30s} {r["exc20"]:>8.4f} {r["dd"]:>8.4f} {exc60s:>8s} {dd_impr:>8.4f} {r["pos"]:>4} {r["strongest"]:>7.4f}')

    out = Path("artifacts/optimization/cn_rounds_21_40_v2/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2, default=str))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    run()
