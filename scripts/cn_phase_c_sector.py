"""CN x1.1 Phase C (Rounds 11-20): Sector-based portfolio + 2026H1 validation + final selection.

Uses actual CN sector classification for genuine sector-based portfolio construction.
"""
from __future__ import annotations

import argparse, json, math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.daily_ranker import prepare_ranker_frame
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import (
    load_window_benchmark_returns, normalize_qlib_frame_index,
)
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
from src.research.window_policy import (
    build_window_sampling_plan, horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker,
)

FACTOR_LIBRARY_PATH = Path("configs/factor_libraries/ohlcv.yaml")
SECTOR_CONFIG = Path("configs/research_classifications/cn130_sector_industry_v1.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/cn_selected_equities_v3.yaml")
DECISION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
BENCHMARK_SYMBOL = "000300"
EXPERIMENT_ID = "cn_x1_1_phase_c_sector_v1"

def _load_yaml(path): d = yaml.safe_load(Path(path).read_text(encoding="utf-8")); return d if isinstance(d, dict) else {}
def _write_json(path, payload): Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
def _compound(values): return math.prod(1.0 + v for v in values) - 1.0

def load_cn_sectors():
    raw = _load_yaml(SECTOR_CONFIG)
    symbols = raw.get("symbols", {})
    return {str(k): str(v.get("sector", "Unknown")) for k, v in symbols.items()}


def get_factor_expressions(groups):
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, groups)
    exprs, seen = [], set()
    for g in selected:
        for f in g.factors:
            if f.expression not in seen:
                exprs.append(f.expression); seen.add(f.expression)
    return exprs


def evaluate_sector_portfolio(scores_df, returns_df, benchmark_df, sector_map, eval_dates,
                               n_sectors=4, names_per_sector=1, cost_bps=20, cadence=10):
    """Genuine sector-based portfolio: pick top N sectors by avg score, then top M names each."""
    rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
    port_returns = []

    for date in rebalance_dates:
        try:
            daily_scores = scores_df.xs(date, level="datetime")
            daily_rets = returns_df.xs(date, level="datetime")
        except KeyError:
            continue

        if len(daily_scores) < n_sectors:
            continue

        # Compute average score per sector
        sector_scores = defaultdict(list)
        for inst, row in daily_scores.iterrows():
            inst_str = str(inst)
            sec = sector_map.get(inst_str, "Unknown")
            sector_scores[sec].append(float(row["score"]))

        sector_avg = {sec: np.mean(scores) for sec, scores in sector_scores.items() if len(scores) >= names_per_sector}

        # Pick top N sectors
        top_sectors = sorted(sector_avg, key=lambda s: sector_avg[s], reverse=True)[:n_sectors]

        # Pick top M names per sector
        selected = []
        for sec in top_sectors:
            sec_stocks = [(inst_str, daily_scores.loc[inst_str, "score"])
                         for inst_str in sector_scores[sec]
                         if str(inst_str) in daily_scores.index]
            sec_stocks.sort(key=lambda x: x[1], reverse=True)
            for inst_str, _ in sec_stocks[:names_per_sector]:
                if inst_str in daily_rets.index:
                    selected.append(inst_str)

        if not selected:
            # Fallback: pick top N*M stocks globally
            ranked = daily_scores.sort_values("score", ascending=False)
            selected = [str(s) for s in ranked.index[:n_sectors * names_per_sector]]

        sel_rets = daily_rets[daily_rets.index.isin(selected)]
        if len(sel_rets) == 0:
            continue
        cost_factor = 1.0 - (cost_bps / 10000.0) / cadence
        port_returns.append(float(sel_rets["return"].mean()) * cost_factor)

    if not port_returns:
        return None
    port_series = pd.Series(port_returns, index=pd.DatetimeIndex([rebalance_dates[i] for i in range(len(port_returns))]))
    common = port_series.index.intersection(benchmark_df.index)
    if len(common) == 0:
        return None
    port_aligned = port_series[common]
    bench_aligned = benchmark_df.loc[common, "return"]

    strategy_compound = _compound([float(r) for r in port_aligned])
    benchmark_compound = _compound([float(r) for r in bench_aligned])
    relative_excess = (1.0 + strategy_compound) / (1.0 + benchmark_compound) - 1.0
    cum = (1.0 + port_aligned).cumprod()
    max_dd = float(((cum - cum.cummax()) / cum.cummax()).min())

    return {
        "strategy_compound": float(strategy_compound),
        "benchmark_compound": float(benchmark_compound),
        "relative_excess": float(relative_excess),
        "max_drawdown": float(max_dd),
        "n_periods": len(port_aligned),
    }


# ===== Phase C Configs (Rounds 11-20) =====

# R11-13: Best ranker configs from Phase A + real sector portfolio grid
RANKER_CONFIGS_C = [
    # (config_id, factor_groups, calibration)
    ("c_baseline", ["cn_balanced_ohlcv"],
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":100,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("c_lower_lr", ["cn_balanced_ohlcv"],
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("c_regularized_volrev", ["cn_balanced_ohlcv", "cn_volatility_reversal"],
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":2.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.1,"reg_lambda":2.0,"seed":42})),
    ("c_sampled_pressure", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
]

# R11-13: Sector portfolio grid (genuine sector-based)
SECTOR_PORTFOLIO_GRID = [
    ("sp_s2_n1", 2, 1),
    ("sp_s3_n1", 3, 1),
    ("sp_s3_n2", 3, 2),
    ("sp_s4_n1", 4, 1),
    ("sp_s4_n2", 4, 2),
    ("sp_s5_n1", 5, 1),
    ("sp_s2_n2", 2, 2),
    ("sp_s5_n2", 5, 2),   # R13: wider diversification
    ("sp_s6_n1", 6, 1),   # R13: broad
    ("sp_top15_eq", None, None),  # R13: pure Top-15 (no sector logic) — baseline comparison
]

# R14-15: Cost stress + additional calibrations
ADDITIONAL_CALS_C = [
    ("c_deep_reg", ["cn_balanced_ohlcv"],
     XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":63,"max_depth":0,"min_child_weight":2.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.1,"reg_lambda":2.0,"seed":42})),
    ("c_light_reg_pressure", ["cn_balanced_ohlcv", "cn_price_volume_pressure"],
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.05,"reg_lambda":1.5,"seed":42})),
]


def run(root, *, provider_uri, output_dir):
    root = root.resolve()
    provider_uri = Path(provider_uri).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    universe = _load_yaml(UNIVERSE_CONFIG)
    sector_map = load_cn_sectors()
    print(f"CN sectors: {len(set(sector_map.values()))} unique, {len(sector_map)} stocks mapped")

    all_combos = RANKER_CONFIGS_C + ADDITIONAL_CALS_C
    print(f"Ranker configs: {len(all_combos)}, Portfolio variants: {len(SECTOR_PORTFOLIO_GRID)}")

    runtime = QlibCNExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    requested = [str(s) for s in universe.get("symbols", [])]
    available = runtime.available_symbols()
    normalized = normalize_market_symbols("cn", requested, available_symbols=available)
    symbols = [item.normalized_symbol for item in normalized if item.normalized_symbol in available]
    print(f"Symbols: {len(symbols)}/{len(requested)}")

    # Pre-compute factor expressions
    config_exprs = {}
    for cid, groups, cal in all_combos:
        config_exprs[cid] = get_factor_expressions(groups)
        print(f"  {cid}: {len(config_exprs[cid])} factors")

    all_exprs_set = set()
    for exprs in config_exprs.values():
        all_exprs_set.update(exprs)
    all_exprs = sorted(all_exprs_set)
    expr_to_idx = {e: i for i, e in enumerate(all_exprs)}

    calendar = runtime.calendar("2021-01-01", "2025-12-31")
    avail_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar, "2021-01-01", avail_end, first_test_year=2024, last_test_year=2025,
        min_complete_windows=4, partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None, horizon_sessions=10, cadence_sessions=10,
    )
    windows = list(window_plan.selected_windows)
    eval_dates_by_window = horizon_eligible_dates_by_window(window_plan, calendar)

    all_results = []
    for window in windows:
        eval_dates = eval_dates_by_window[window.label]
        print(f"\n{'='*60}")
        print(f"Phase C - Window: {window.label} ({len(eval_dates)} eval dates)")

        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, all_exprs, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{i}" for i in range(len(all_exprs))]

        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        )
        returns_all.columns = ["return"]

        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = dates.isin(eval_dates)

        benchmark = load_window_benchmark_returns(
            runtime, benchmark_instrument=BENCHMARK_SYMBOL, return_expression=RETURN_EXPRESSION,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        for cid, groups, cal in all_combos:
            expr_indices = [expr_to_idx[e] for e in config_exprs[cid]]
            n_factors = len(expr_indices)

            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(n_factors)]
            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{cid}")
            if not valid:
                continue

            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal)
            cf_test = features_all.loc[test_mask].iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(n_factors)]
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)

            # Evaluate all portfolio variants × cost levels
            for sp_label, n_sec, n_names in SECTOR_PORTFOLIO_GRID:
                for cost_bps in (20, 40, 60):
                    if sp_label == "sp_top15_eq":
                        # Pure Top-15 without sector logic
                        result = evaluate_sector_portfolio(
                            scores, returns_all.loc[test_mask].copy(), benchmark,
                            {s: "All" for s in symbols}, eval_dates,
                            n_sectors=1, names_per_sector=15, cost_bps=cost_bps,
                        )
                    else:
                        result = evaluate_sector_portfolio(
                            scores, returns_all.loc[test_mask].copy(), benchmark,
                            sector_map, eval_dates,
                            n_sectors=n_sec, names_per_sector=n_names, cost_bps=cost_bps,
                        )
                    if result is None: continue
                    result["config_id"] = cid
                    result["portfolio"] = sp_label
                    result["window"] = window.label
                    result["cost_bps"] = cost_bps
                    result["n_factors"] = n_factors
                    result["n_sectors"] = n_sec
                    result["names_per_sector"] = n_names
                    all_results.append(result)

        # Top-5 for this window
        w20 = [r for r in all_results if r["window"] == window.label and r["cost_bps"] == 20]
        w20.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"  Top-5 ({window.label}, 20bps):")
        for r in w20[:5]:
            print(f"    {r['config_id']}_{r['portfolio']:<35s} exc={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # ---- Cross-window aggregation ----
    print(f"\n{'='*60}")
    print("PHASE C: Cross-Window Aggregation (20bps)")

    by_combo = defaultdict(lambda: {"windows": {}, "costs": defaultdict(list)})
    for r in all_results:
        cid = f"{r['config_id']}__{r['portfolio']}"
        cost = r["cost_bps"]
        by_combo[cid]["costs"][cost].append(r)
        if cost == 20:
            by_combo[cid]["windows"][r["window"]] = r

    agg = []
    for cid, data in by_combo.items():
        win_data = data["windows"]
        if len(win_data) != 4: continue
        ordered = [win_data[w] for w in DECISION_WINDOWS]
        strategy_nav = math.prod(1.0 + r["strategy_compound"] for r in ordered)
        bench_nav = math.prod(1.0 + r["benchmark_compound"] for r in ordered)
        compounded_rel_excess = strategy_nav / bench_nav - 1.0
        worst_dd = min(r["max_drawdown"] for r in ordered)
        positive = sum(1 for r in ordered if r["relative_excess"] > 0)

        # 40/60bps check
        exc_60 = None; exc_40 = None
        for cost in (40, 60):
            if cost in data["costs"] and len(data["costs"][cost]) == 4:
                oc = sorted(data["costs"][cost], key=lambda x: DECISION_WINDOWS.index(x["window"]))
                val = math.prod(1.0 + r["strategy_compound"] for r in oc) / math.prod(1.0 + r["benchmark_compound"] for r in oc) - 1.0
                if cost == 40: exc_40 = val
                else: exc_60 = val

        strongest = max(r["relative_excess"] for r in ordered) / sum(
            r["relative_excess"] for r in ordered if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in ordered if r["relative_excess"] > 0) > 0 else 1.0

        agg.append({
            "combo_id": cid,
            "config_id": ordered[0]["config_id"],
            "portfolio": ordered[0]["portfolio"],
            "n_sectors": ordered[0].get("n_sectors"),
            "names_per_sector": ordered[0].get("names_per_sector"),
            "n_factors": ordered[0]["n_factors"],
            "compounded_relative_excess_20": compounded_rel_excess,
            "compounded_relative_excess_40": exc_40,
            "compounded_relative_excess_60": exc_60,
            "worst_drawdown_20": worst_dd,
            "positive_windows": positive,
            "strongest_share": strongest,
            "per_window": {r["window"]: {"excess": r["relative_excess"], "dd": r["max_drawdown"]} for r in ordered},
        })

    # Find baseline
    baseline = next((r for r in agg if r["combo_id"] == "c_baseline__sp_s4_n1"), None)
    if baseline:
        base_dd = baseline["worst_drawdown_20"]
        base_excess = baseline["compounded_relative_excess_20"]
        print(f"Baseline (c_baseline__sp_s4_n1 = CN x1.1): DD={base_dd:.4f}, Excess={base_excess:.4f}")
    else:
        base_dd, base_excess = -0.30, 0.0

    # Gate analysis
    dd_threshold = base_dd + 0.03 if baseline else -0.22
    passing = []
    for r in agg:
        dd_gate = r["worst_drawdown_20"] >= dd_threshold or r["worst_drawdown_20"] >= -0.22
        exc_gate_20 = r["compounded_relative_excess_20"] >= 0.90 * base_excess
        exc_gate_60 = r["compounded_relative_excess_60"] is not None and r["compounded_relative_excess_60"] > 0
        share_gate = r["strongest_share"] < 0.55
        pos_gate = r["positive_windows"] == 4
        all_pass = dd_gate and exc_gate_20 and exc_gate_60 and share_gate and pos_gate
        r["gates"] = {"DD": dd_gate, "pos": pos_gate, "share": share_gate, "exc20": exc_gate_20, "exc60": exc_gate_60}
        r["all_pass"] = all_pass
        if all_pass:
            passing.append(r)

    # Sort all by excess
    agg.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)

    print(f"\nTop-20 Results (by excess@20):")
    print(f"{'Rank':<5} {'Combo':<45s} {'Exc@20':>8s} {'DD@20':>8s} {'Exc@60':>8s} {'DD_Impr':>8s} {'Pos':>4s} {'AllPass':>7s}")
    print("-" * 135)
    for i, r in enumerate(agg[:20]):
        exc60_s = f'{r["compounded_relative_excess_60"]:.4f}' if r["compounded_relative_excess_60"] else 'N/A'
        dd_impr = (base_dd - r["worst_drawdown_20"]) if baseline else 0
        print(f"{i+1:<5} {r['combo_id']:<45s} {r['compounded_relative_excess_20']:>8.4f} {r['worst_drawdown_20']:>8.4f} {exc60_s:>8s} {dd_impr:>8.4f} {r['positive_windows']:>4} {str(r['all_pass']):>7s}")

    print(f"\nGate-Passing Candidates: {len(passing)}")
    passing.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)
    for r in passing[:10]:
        print(f"  {r['combo_id']:<45s} exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} dd_impr={(base_dd - r['worst_drawdown_20']):+.4f}")

    # Per-window for top-3 passing
    top3_pass = passing[:3]
    if top3_pass:
        print(f"\nPer-window detail for top-3 passing:")
        for r in top3_pass:
            print(f"\n  {r['combo_id']} (exc@20={r['compounded_relative_excess_20']:.4f}, dd={r['worst_drawdown_20']:.4f}):")
            for w in DECISION_WINDOWS:
                pw = r["per_window"].get(w, {})
                print(f"    {w}: exc={pw.get('excess',0):.4f} dd={pw.get('dd',0):.4f}")

    # ---- R18: 2026H1 validation on top-3 ----
    print(f"\n{'='*60}")
    print("R18: 2026H1 Validation (top-3 passing)")

    calendar_26 = runtime.calendar("2021-01-01", "2026-06-30")
    avail_end_26 = min(pd.Timestamp("2026-06-30"), calendar_26.max()).strftime("%Y-%m-%d")
    wp_26 = build_window_sampling_plan(
        calendar_26, "2021-01-01", avail_end_26, first_test_year=2026, last_test_year=2026,
        min_complete_windows=1, partial_window_policy="allow_horizon_contained_partial_final_window",
        min_partial_window_eligible_sessions=10, horizon_sessions=10, cadence_sessions=10,
    )
    w26 = list(wp_26.selected_windows)
    if w26:
        eval_26 = horizon_eligible_dates_by_window(wp_26, calendar_26).get(w26[0].label, pd.DatetimeIndex([]))
        print(f"2026H1: {w26[0].train_start}..{w26[0].train_end}, {len(eval_26)} eval dates")

        for r in top3_pass[:3]:
            cid = r["config_id"]
            pfx = r["portfolio"]
            # Find config
            cfg = next((c for c in all_combos if c[0] == cid), None)
            if cfg is None: continue
            _, groups, cal = cfg
            exprs = config_exprs[cid]
            expr_indices = [expr_to_idx[e] for e in exprs]

            try:
                feats_26 = normalize_qlib_frame_index(
                    runtime.features(symbols, exprs, "2021-01-01", "2026-06-30")
                ).replace([np.inf, -np.inf], np.nan)
                feats_26.columns = [f"feature_{i}" for i in range(len(exprs))]
                rets_26 = normalize_qlib_frame_index(
                    runtime.features(symbols, [RETURN_EXPRESSION], "2021-01-01", "2026-06-30")
                )
                rets_26.columns = ["return"]

                d26 = feats_26.index.get_level_values("datetime")
                tm_26 = (d26 >= pd.Timestamp(w26[0].train_start)) & (d26 <= pd.Timestamp(w26[0].train_end))
                testm_26 = d26.isin(eval_26)
                ft_tr = feats_26.loc[tm_26].copy(); rt_tr = rets_26.loc[tm_26].copy()
                ft_tr, rt_tr = purge_training_tail(ft_tr, rt_tr, holding_days=10)
                valid, reason = validate_no_nan_inputs(ft_tr, context=f"2026H1/{cid}")
                if not valid:
                    print(f"  SKIP {cid}: {reason}")
                    continue

                x_r, y_r, g_r = prepare_ranker_frame(ft_tr, rt_tr)
                fitted = fit_xgb_native_daily_ranker(x_r, y_r, g_r, calibration=cal)
                ft_test = feats_26.loc[testm_26].copy()
                sc_26 = predict_xgb_native_daily_ranker(fitted, ft_test)

                bm_26 = load_window_benchmark_returns(
                    runtime, benchmark_instrument=BENCHMARK_SYMBOL, return_expression=RETURN_EXPRESSION,
                    evaluation_dates=eval_26,
                    start=eval_26.min().strftime("%Y-%m-%d"),
                    end=eval_26.max().strftime("%Y-%m-%d"),
                    provenance="raw_forward_return", horizon=10,
                )

                if r["portfolio"] == "sp_top15_eq":
                    result_26 = evaluate_sector_portfolio(
                        sc_26, rets_26.loc[testm_26].copy(), bm_26,
                        {s: "All" for s in symbols}, eval_26, n_sectors=1, names_per_sector=15,
                    )
                else:
                    n_sec = r.get("n_sectors", 4)
                    n_nam = r.get("names_per_sector", 1)
                    result_26 = evaluate_sector_portfolio(
                        sc_26, rets_26.loc[testm_26].copy(), bm_26,
                        sector_map, eval_26, n_sectors=n_sec, names_per_sector=n_nam,
                    )
                if result_26:
                    print(f"  {cid}__{pfx}: 2026H1 exc={result_26['relative_excess']:.4f} dd={result_26['max_drawdown']:.4f}")
                    r["reporting_2026H1"] = result_26
            except Exception as e:
                print(f"  {cid}: ERROR {e}")

    # Save
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "rounds": "11-20",
        "configs_tested": len(all_combos),
        "portfolio_variants": len(SECTOR_PORTFOLIO_GRID),
        "cost_levels": [20, 40, 60],
        "aggregated": agg,
        "gate_passing": passing,
        "baseline_dd": base_dd if baseline else None,
        "baseline_excess": base_excess if baseline else None,
    }
    _write_json(output_dir / "cn_phase_c_sector.json", payload)
    print(f"\nSaved to {output_dir / 'cn_phase_c_sector.json'}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider-uri", type=Path, default=Path("data/providers/cn"))
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/cn_x1_1_phase_c_sector_v1"))
    args = p.parse_args()
    run(Path.cwd(), provider_uri=args.provider_uri, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
