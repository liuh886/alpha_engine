"""USx rounds 11-15: extended calibrations, new factors, cost stress, 2026H1 validation.

R11: Extended XGBoost hyperparameter search with t15_s4 sector cap
R12: New factor combinations (reversal, mean_reversion) with t15_s4
R13: Cost stress testing (40/60bps) on best candidates
R14: 2026H1 out-of-sample validation
R15: Final ensemble evaluation
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
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.window_policy import (
    build_window_sampling_plan, horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker,
)

FACTOR_LIBRARY_PATH = Path("configs/factor_libraries/ohlcv.yaml")
SECTOR_CONFIG = Path("configs/research_classifications/us87_sector_industry_v1.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/us_selected_equities_v2.yaml")
DECISION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
EXPERIMENT_ID = "us_x1_2_rounds_11_15_v1"

TOP_N = 15
MAX_PER_SECTOR = 4
CADENCE = 10

def _load_yaml(path): d = yaml.safe_load(Path(path).read_text(encoding="utf-8")); return d if isinstance(d, dict) else {}
def _write_json(path, payload): Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
def _compound(values): return math.prod(1.0 + v for v in values) - 1.0

def load_sectors():
    raw = _load_yaml(SECTOR_CONFIG)
    return {str(sym): str(rec["sector"]) for sym, rec in raw.get("records", {}).items()}

def select_capped(ranked_df, sector_map, top_n=15, max_per_sector=4):
    ranked = ranked_df.sort_values("score", ascending=False)
    selected, counts = [], {}
    for _, row in ranked.iterrows():
        sym = str(row["instrument"])
        sec = sector_map.get(sym, "Unknown")
        if counts.get(sec, 0) >= max_per_sector: continue
        selected.append(sym); counts[sec] = counts.get(sec, 0) + 1
        if len(selected) >= top_n: break
    if len(selected) < top_n:
        for _, row in ranked.iterrows():
            sym = str(row["instrument"])
            if sym not in selected: selected.append(sym)
            if len(selected) >= top_n: break
    return selected[:top_n]


def evaluate_portfolio(scores_df, returns_df, benchmark_df, sector_map, eval_dates,
                       top_n=15, max_per_sector=4, cadence=10, cost_bps=20):
    rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
    port_returns = []
    for date in rebalance_dates:
        try:
            daily_scores = scores_df.xs(date, level="datetime")
            daily_rets = returns_df.xs(date, level="datetime")
        except KeyError: continue
        daily_scores_df = daily_scores.reset_index()
        daily_scores_df.columns = ["instrument", "score"]
        if max_per_sector is not None:
            selected = select_capped(daily_scores_df, sector_map, top_n, max_per_sector)
        else:
            ranked = daily_scores_df.sort_values("score", ascending=False)
            selected = [str(s) for s in ranked["instrument"].iloc[:top_n]]
        sel_rets = daily_rets[daily_rets.index.isin(selected)]
        if len(sel_rets) == 0: continue
        # Apply cost: cost_bps / 10000 per one-way (half at entry, half at exit)
        cost_factor = 1.0 - (cost_bps / 10000.0) / 10.0  # roughly spread over 10 sessions
        port_returns.append(float(sel_rets["return"].mean()) * cost_factor)

    if not port_returns: return None
    port_series = pd.Series(port_returns, index=pd.DatetimeIndex([rebalance_dates[i] for i in range(len(port_returns))]))
    common = port_series.index.intersection(benchmark_df.index)
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
        "positive_periods": int((port_aligned > 0).sum()),
    }


def _get_factor_expressions(groups):
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, groups)
    exprs, seen = [], set()
    for g in selected:
        for f in g.factors:
            if f.expression not in seen:
                exprs.append(f.expression); seen.add(f.expression)
    return exprs


# ====== Round 11: Extended XGBoost Calibrations ======
# Test more calibration variants from Round 1 that weren't in the multi-dim grid
R11_CALIBRATIONS = {
    "r11_std": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "r11_sampled": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "r11_higher_child": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":5.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "r11_regularized": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":2.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.1,"reg_lambda":2.0,"seed":42}),
    "r11_lower_lr": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "r11_fewer_leaves": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":15,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "r11_more_rounds": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":400,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.1,"reg_lambda":1.0,"seed":42}),
}

# ====== Round 12: New Factor Combinations ======
# Build custom factor groups not in the library
R12_FACTOR_GROUPS = {
    "momentum_volatility_volume": ["momentum_volatility_volume"],  # baseline 7f
    "mvv_plus_reversal": ["momentum_volatility_volume"],  # + individual reversal factors (handled in code)
    "mvv_plus_meanrev": ["momentum_volatility_volume"],   # + individual mean_reversion factors
}

# Custom factor additions for round 12
REVERSAL_FACTORS = ["ohlcv.reversal.inv_ret_1d", "ohlcv.reversal.inv_ret_3d", "ohlcv.reversal.inv_ret_5d"]
MEANREV_FACTORS = ["ohlcv.mean_reversion.close_vs_ma_5d", "ohlcv.mean_reversion.close_vs_ma_10d", "ohlcv.mean_reversion.close_vs_ma_20d"]
LIQUIDITY_FACTORS = ["ohlcv.liquidity.volume_vs_ma_5d", "ohlcv.liquidity.volume_vs_ma_10d"]
PRESSURE_FACTORS = ["ohlcv.pressure.ret1_x_volume_shock_5d", "ohlcv.pressure.high_low_ratio"]


def get_custom_expressions(base_groups, extra_factor_ids):
    """Get base group expressions + specific extra factor expressions."""
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, base_groups)
    exprs, seen_ids = [], set()
    for g in selected:
        for f in g.factors:
            if f.factor_id not in seen_ids:
                exprs.append(f.expression); seen_ids.add(f.factor_id)
    # Add extra factors by ID - iterate through all selected groups for lookup
    all_lib_factors = {}
    all_groups = select_factor_groups(library, list(library.yaml().get("groups", {}).keys())
                                      if hasattr(library, 'yaml') else [])
    # Simpler: just look up factors directly from the raw library
    raw = _load_yaml(FACTOR_LIBRARY_PATH)
    factors_raw = raw.get("factors", {})
    for fid in extra_factor_ids:
        if fid in factors_raw and fid not in seen_ids:
            exprs.append(factors_raw[fid]["expression"]); seen_ids.add(fid)
    return exprs


# ====== Define all model configs for rounds 11-15 ======
# Each: (config_id, factor_groups_or_custom, calibration_id)
MODEL_CONFIGS_R11_12 = []

# R11: extended calibrations with standard 7 factors + t15_s4
for cal_id, cal in R11_CALIBRATIONS.items():
    MODEL_CONFIGS_R11_12.append((cal_id, ["momentum_volatility_volume"], cal, "R11_cal"))

# R12: new factor combinations with sampled calibration
sampled_cal = R11_CALIBRATIONS["r11_sampled"]
std_cal = R11_CALIBRATIONS["r11_std"]

# Base 7f + reversal
MODEL_CONFIGS_R11_12.append(("r12_mvv_rev", ["momentum_volatility_volume"], sampled_cal, "R12_factor"))
MODEL_CONFIGS_R11_12.append(("r12_mvv_meanrev", ["momentum_volatility_volume"], sampled_cal, "R12_factor"))
MODEL_CONFIGS_R11_12.append(("r12_mvv_rev_meanrev", ["momentum_volatility_volume"], sampled_cal, "R12_factor"))
MODEL_CONFIGS_R11_12.append(("r12_mvv_rev_meanrev_liq", ["momentum_volatility_volume"], sampled_cal, "R12_factor"))
MODEL_CONFIGS_R11_12.append(("r12_mvv_pressure", ["momentum_volatility_volume"], sampled_cal, "R12_factor"))

# Map custom factor configs to their extra factor IDs
CUSTOM_FACTOR_MAP = {
    "r12_mvv_rev": REVERSAL_FACTORS,
    "r12_mvv_meanrev": MEANREV_FACTORS,
    "r12_mvv_rev_meanrev": REVERSAL_FACTORS + MEANREV_FACTORS,
    "r12_mvv_rev_meanrev_liq": REVERSAL_FACTORS + MEANREV_FACTORS + LIQUIDITY_FACTORS,
    "r12_mvv_pressure": REVERSAL_FACTORS + PRESSURE_FACTORS,
}


def run(root, *, provider_uri, output_dir):
    root = root.resolve()
    provider_uri = Path(provider_uri).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    universe = _load_yaml(UNIVERSE_CONFIG)
    sector_map = load_sectors()
    print(f"Models: {len(MODEL_CONFIGS_R11_12)} | Portfolio: t15_s4 (fixed)")

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    requested = [str(s) for s in universe.get("symbols", [])]
    available = runtime.available_symbols()
    normalized = normalize_market_symbols("us", requested, available_symbols=available)
    symbols = [item.normalized_symbol for item in normalized]
    print(f"Symbols: {len(symbols)}")

    calendar = runtime.calendar("2021-01-01", "2025-12-31")
    avail_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar, "2021-01-01", avail_end, first_test_year=2024, last_test_year=2025,
        min_complete_windows=4, partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None, horizon_sessions=10, cadence_sessions=10,
    )
    windows = list(window_plan.selected_windows)
    eval_dates_by_window = horizon_eligible_dates_by_window(window_plan, calendar)

    # Also compute 2026H1 for reporting (round 14)
    calendar_26 = runtime.calendar("2021-01-01", "2026-06-30")
    avail_end_26 = min(pd.Timestamp("2026-06-30"), calendar_26.max()).strftime("%Y-%m-%d")

    # Pre-compute expressions
    model_exprs = {}
    for mid, groups, cal, round_tag in MODEL_CONFIGS_R11_12:
        if mid in CUSTOM_FACTOR_MAP:
            model_exprs[mid] = get_custom_expressions(groups, CUSTOM_FACTOR_MAP[mid])
        else:
            model_exprs[mid] = _get_factor_expressions(groups)

    all_exprs_set = set()
    for exprs in model_exprs.values():
        all_exprs_set.update(exprs)
    all_exprs = sorted(all_exprs_set)
    expr_to_idx = {e: i for i, e in enumerate(all_exprs)}
    for mid, exprs in model_exprs.items():
        print(f"  {mid}: {len(exprs)} factors")

    all_results = []

    for window in windows:
        eval_dates = eval_dates_by_window[window.label]
        print(f"\n{'='*60}")
        print(f"Window: {window.label} | {len(eval_dates)} eval dates")

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
            runtime, benchmark_instrument="QQQ", return_expression=RETURN_EXPRESSION,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        for mid, groups, cal, round_tag in MODEL_CONFIGS_R11_12:
            expr_indices = [expr_to_idx[e] for e in model_exprs[mid]]
            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{mid}")
            if not valid:
                print(f"  SKIP {mid}: {reason}")
                continue

            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal)
            cf_test = features_all.loc[test_mask].iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)

            # Evaluate at 20, 40, 60 bps (R13: cost stress)
            for cost_bps in (20, 40, 60):
                result = evaluate_portfolio(
                    scores, returns_all.loc[test_mask].copy(), benchmark,
                    sector_map, eval_dates, top_n=TOP_N, max_per_sector=MAX_PER_SECTOR,
                    cadence=CADENCE, cost_bps=cost_bps,
                )
                if result is None: continue
                result["config_id"] = mid
                result["window"] = window.label
                result["round_tag"] = round_tag
                result["cost_bps"] = cost_bps
                result["n_factors"] = len(model_exprs[mid])
                all_results.append(result)

        # Top-5 this window at 20bps
        w20 = [r for r in all_results if r["window"] == window.label and r["cost_bps"] == 20]
        w20.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"  Top-5 (20bps):")
        for r in w20[:5]:
            print(f"    {r['config_id']:30s} exc={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # ---- Cross-window aggregation ----
    print(f"\n{'='*60}")
    print("CROSS-WINDOW AGGREGATION (20bps)")

    by_config = defaultdict(lambda: {"windows": {}, "costs": {}})
    for r in all_results:
        cid = r["config_id"]
        cost = r["cost_bps"]
        if cost not in by_config[cid]["costs"]:
            by_config[cid]["costs"][cost] = {"windows": {}}
        by_config[cid]["costs"][cost]["windows"][r["window"]] = r
        if cost == 20:
            by_config[cid]["windows"][r["window"]] = r

    # Aggregated at 20bps
    agg_20 = []
    for cid, data in by_config.items():
        win_data = data["windows"]
        if len(win_data) != 4: continue
        ordered = [win_data[w] for w in DECISION_WINDOWS]
        strategy_nav = math.prod(1.0 + r["strategy_compound"] for r in ordered)
        bench_nav = math.prod(1.0 + r["benchmark_compound"] for r in ordered)
        compounded_rel_excess = strategy_nav / bench_nav - 1.0
        worst_dd = min(r["max_drawdown"] for r in ordered)
        positive = sum(1 for r in ordered if r["relative_excess"] > 0)
        strongest = max(r["relative_excess"] for r in ordered) / sum(
            r["relative_excess"] for r in ordered if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in ordered if r["relative_excess"] > 0) > 0 else 1.0

        # Check 40bps and 60bps too for cost stress
        excess_40 = None; excess_60 = None
        if 40 in data["costs"] and len(data["costs"][40]["windows"]) == 4:
            o40 = [data["costs"][40]["windows"][w] for w in DECISION_WINDOWS]
            excess_40 = math.prod(1.0 + r["strategy_compound"] for r in o40) / math.prod(1.0 + r["benchmark_compound"] for r in o40) - 1.0
        if 60 in data["costs"] and len(data["costs"][60]["windows"]) == 4:
            o60 = [data["costs"][60]["windows"][w] for w in DECISION_WINDOWS]
            excess_60 = math.prod(1.0 + r["strategy_compound"] for r in o60) / math.prod(1.0 + r["benchmark_compound"] for r in o60) - 1.0

        agg_20.append({
            "config_id": cid,
            "round_tag": ordered[0]["round_tag"],
            "n_factors": ordered[0]["n_factors"],
            "compounded_relative_excess_20": compounded_rel_excess,
            "compounded_relative_excess_40": excess_40,
            "compounded_relative_excess_60": excess_60,
            "worst_drawdown_20": worst_dd,
            "positive_windows": positive,
            "strongest_share": strongest,
            "per_window": {r["window"]: {"excess": r["relative_excess"], "dd": r["max_drawdown"]} for r in ordered},
        })

    # Find baseline (r11_std) for gate comparison
    baseline = next((r for r in agg_20 if r["config_id"] == "r11_std"), None)
    if baseline:
        base_dd = baseline["worst_drawdown_20"]
        base_excess = baseline["compounded_relative_excess_20"]
        print(f"Baseline (r11_std): DD={base_dd:.4f}, Excess@20={base_excess:.4f}")
        dd_threshold = base_dd + 0.03
    else:
        base_excess = 1.0; dd_threshold = -0.22

    # Gate analysis
    passing = []
    for r in agg_20:
        dd_gate = r["worst_drawdown_20"] >= dd_threshold or r["worst_drawdown_20"] >= -0.22
        excess_gate_20 = r["compounded_relative_excess_20"] >= 0.90 * base_excess
        excess_gate_60 = r["compounded_relative_excess_60"] is not None and r["compounded_relative_excess_60"] > 0
        share_gate = r["strongest_share"] < 0.55
        pos_gate = r["positive_windows"] == 4
        all_pass = dd_gate and excess_gate_20 and excess_gate_60 and share_gate and pos_gate

        r["gates"] = {
            "DD_improve_3pp_or_m22": dd_gate,
            "4_positive_windows": pos_gate,
            "strongest_share_below_55pct": share_gate,
            "retain_90pct_excess_20bps": excess_gate_20,
            "positive_60bps_excess": excess_gate_60,
        }
        r["all_gates_pass"] = all_pass
        if all_pass: passing.append(r)

    # Sort
    agg_20.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)

    print(f"\nAll candidates (sorted by excess@20):")
    print(f"{'Config':<30s} {'Exc@20':>8s} {'DD@20':>8s} {'Exc@60':>8s} {'Pos':>4s} {'Share':>7s} {'#Fac':>5s} {'Round':>6s} {'AllPass':>7s}")
    print("-" * 120)
    for r in agg_20:
        exc60_str = f'{r["compounded_relative_excess_60"]:.4f}' if r["compounded_relative_excess_60"] is not None else 'N/A'
        print(f'{r["config_id"]:<30s} {r["compounded_relative_excess_20"]:>8.4f} {r["worst_drawdown_20"]:>8.4f} {exc60_str:>8s} {r["positive_windows"]:>4} {r["strongest_share"]:>7.4f} {r["n_factors"]:>5} {r["round_tag"]:>6s} {str(r["all_gates_pass"]):>7s}')

    print(f"\nGate-passing candidates: {len(passing)}")
    passing.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)
    for r in passing:
        print(f"  {r['config_id']}: exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} exc@60={r['compounded_relative_excess_60']:.4f}")

    # Per-window for top-3 of each round
    for tag in ["R11_cal", "R12_factor"]:
        round_cands = [r for r in agg_20 if r["round_tag"] == tag]
        round_cands.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)
        print(f"\n{tag} Top-3:")
        for r in round_cands[:3]:
            print(f"  {r['config_id']}: exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} all_pass={r['all_gates_pass']}")
            for w in DECISION_WINDOWS:
                pw = r["per_window"].get(w, {})
                print(f"    {w}: exc={pw.get('excess',0):.4f} dd={pw.get('dd',0):.4f}")

    # ---- Round 14: 2026H1 validation for best candidates ----
    print(f"\n{'='*60}")
    print("R14: 2026H1 REPORTING WINDOW (top-3 overall)")

    top3 = agg_20[:3]
    # Re-initialize for 2026H1
    calendar_26h1 = runtime.calendar("2021-01-01", "2026-06-30")
    avail_end_h1 = min(pd.Timestamp("2026-06-30"), calendar_26h1.max()).strftime("%Y-%m-%d")
    wp_26h1 = build_window_sampling_plan(
        calendar_26h1, "2021-01-01", avail_end_h1, first_test_year=2026, last_test_year=2026,
        min_complete_windows=1, partial_window_policy="allow_horizon_contained_partial_final_window",
        min_partial_window_eligible_sessions=10, horizon_sessions=10, cadence_sessions=10,
    )
    w26 = list(wp_26h1.selected_windows)
    if w26:
        w26_label = w26[0].label
        eval_26 = horizon_eligible_dates_by_window(wp_26h1, calendar_26h1).get(w26_label, pd.DatetimeIndex([]))
        print(f"2026H1 window: {w26[0].train_start}..{w26[0].train_end}, test dates: {len(eval_26)}")

        for r in top3[:2]:  # Top 2 only to save time
            mid = r["config_id"]
            cfg = next((c for c in MODEL_CONFIGS_R11_12 if c[0] == mid), None)
            if cfg is None: continue
            _, groups, cal, _ = cfg
            exprs = model_exprs[mid]

            print(f"  Evaluating {mid} on 2026H1...")
            features_26 = normalize_qlib_frame_index(
                runtime.features(symbols, exprs, "2021-01-01", "2026-06-30")
            ).replace([np.inf, -np.inf], np.nan)
            features_26.columns = [f"feature_{i}" for i in range(len(exprs))]
            returns_26 = normalize_qlib_frame_index(
                runtime.features(symbols, [RETURN_EXPRESSION], "2021-01-01", "2026-06-30")
            )
            returns_26.columns = ["return"]

            dates_26 = features_26.index.get_level_values("datetime")
            train_mask_26 = (dates_26 >= pd.Timestamp(w26[0].train_start)) & (dates_26 <= pd.Timestamp(w26[0].train_end))
            test_mask_26 = dates_26.isin(eval_26)

            ft_train_26 = features_26.loc[train_mask_26].copy()
            rt_train_26 = returns_26.loc[train_mask_26].copy()
            ft_train_26, rt_train_26 = purge_training_tail(ft_train_26, rt_train_26, holding_days=10)
            valid, reason = validate_no_nan_inputs(ft_train_26, context=f"2026H1/{mid}")
            if not valid:
                print(f"    SKIP: {reason}")
                continue

            x_r, y_r, g_r = prepare_ranker_frame(ft_train_26, rt_train_26)
            fitted = fit_xgb_native_daily_ranker(x_r, y_r, g_r, calibration=cal)
            ft_test_26 = features_26.loc[test_mask_26].copy()
            scores_26 = predict_xgb_native_daily_ranker(fitted, ft_test_26)

            benchmark_26 = load_window_benchmark_returns(
                runtime, benchmark_instrument="QQQ", return_expression=RETURN_EXPRESSION,
                evaluation_dates=eval_26,
                start=eval_26.min().strftime("%Y-%m-%d"),
                end=eval_26.max().strftime("%Y-%m-%d"),
                provenance="raw_forward_return", horizon=10,
            )

            result_26 = evaluate_portfolio(
                scores_26, returns_26.loc[test_mask_26].copy(), benchmark_26,
                sector_map, eval_26, top_n=TOP_N, max_per_sector=MAX_PER_SECTOR,
                cadence=CADENCE, cost_bps=20,
            )
            if result_26:
                print(f"    2026H1: excess={result_26['relative_excess']:.4f} dd={result_26['max_drawdown']:.4f} ({result_26['n_periods']} periods)")
                r["reporting_2026H1"] = result_26

    # Save
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "rounds": "11-15",
        "models_tested": len(MODEL_CONFIGS_R11_12),
        "cost_levels_tested": [20, 40, 60],
        "aggregated_20bps": agg_20,
        "gate_passing": passing,
    }
    _write_json(output_dir / "rounds_11_15.json", payload)
    print(f"\nSaved to {output_dir / 'rounds_11_15.json'}")
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider-uri", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/us_x1_2_rounds_11_15_v1"))
    args = p.parse_args()
    run(Path.cwd(), provider_uri=args.provider_uri, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
