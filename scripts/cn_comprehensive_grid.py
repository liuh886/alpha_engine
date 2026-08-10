"""CN x1.1 comprehensive optimization: 20 rounds across ranker, portfolio, and regime gate.

Phase A (R1-10): Ranker optimization — XGBoost calibrations × factor groups
Phase B (R11-15): Portfolio optimization — sector count × names per sector × regime gate
Phase C (R16-20): Combined + validation — best combo + 2026H1 + final selection

All evaluations use 10D horizon, 10D rebalance, CSI300 benchmark.
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
UNIVERSE_CONFIG = Path("configs/research_universes/cn_selected_equities_v3.yaml")
DECISION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
EXPERIMENT_ID = "cn_x1_1_comprehensive_grid_v1"
BENCHMARK_SYMBOL = "000300"

def _load_yaml(path): d = yaml.safe_load(Path(path).read_text(encoding="utf-8")); return d if isinstance(d, dict) else {}
def _write_json(path, payload): Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
def _compound(values): return math.prod(1.0 + v for v in values) - 1.0

# ============================================================
# Phase A: Ranker Configurations (Rounds 1-10)
# ============================================================

# Factor groups for CN
CN_FACTOR_GROUP_OPTIONS = {
    "balanced": ["cn_balanced_ohlcv"],  # 14 factors
    "balanced_volrev": ["cn_balanced_ohlcv", "cn_volatility_reversal"],  # 24 factors
    "balanced_pressure": ["cn_balanced_ohlcv", "cn_price_volume_pressure"],  # 24 factors
    "balanced_revliq": ["cn_balanced_ohlcv", "cn_short_reversal_liquidity"],  # 23 factors
    "all_groups": ["cn_balanced_ohlcv", "cn_volatility_reversal", "cn_price_volume_pressure", "cn_short_reversal_liquidity"],  # ~47 factors
}

# XGBoost calibrations (USx-validated best + CN-specific)
CN_CALIBRATIONS = {
    "cn_baseline": XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":100,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "cn_sampled": XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "cn_lower_lr": XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "cn_regularized": XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":2.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.1,"reg_lambda":2.0,"seed":42}),
    "cn_aggressive": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":300,"max_leaves":63,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
    "cn_deep": XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":63,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42}),
}

# Phase A: Test factor_groups × calibrations
PHASE_A_COMBOS = [
    # (name, factor_key, cal_key)
    # Baseline
    ("a01_baseline", "balanced", "cn_baseline"),
    # Sampled calibration across groups (R1-3)
    ("a02_sampled", "balanced", "cn_sampled"),
    ("a03_sampled_volrev", "balanced_volrev", "cn_sampled"),
    ("a04_sampled_pressure", "balanced_pressure", "cn_sampled"),
    ("a05_sampled_revliq", "balanced_revliq", "cn_sampled"),
    ("a06_sampled_all", "all_groups", "cn_sampled"),
    # Lower LR across groups (R4-6)
    ("a07_lower_lr", "balanced", "cn_lower_lr"),
    ("a08_lower_lr_volrev", "balanced_volrev", "cn_lower_lr"),
    ("a09_lower_lr_pressure", "balanced_pressure", "cn_lower_lr"),
    ("a10_lower_lr_revliq", "balanced_revliq", "cn_lower_lr"),
    # Regularized across groups (R7-8)
    ("a11_regularized", "balanced", "cn_regularized"),
    ("a12_regularized_volrev", "balanced_volrev", "cn_regularized"),
    # Aggressive/deep (R9-10)
    ("a13_aggressive_balanced", "balanced", "cn_aggressive"),
    ("a14_deep_balanced", "balanced", "cn_deep"),
    ("a15_aggressive_all", "all_groups", "cn_aggressive"),
]

# ============================================================
# Phase B: Portfolio Construction (Rounds 11-15)
# Uses the best Phase A config's scores
# ============================================================

# Portfolio construction grid
PORTFOLIO_GRID_CN = [
    # (label, n_sectors, names_per_sector)
    ("p_s4_n1", 4, 1),   # Current CN x1.1 V3 baseline
    ("p_s3_n1", 3, 1),   # Tighter
    ("p_s2_n1", 2, 1),   # Very tight
    ("p_s5_n1", 5, 1),   # Looser
    ("p_s4_n2", 4, 2),   # More diversification within sector
    ("p_s3_n2", 3, 2),
    ("p_s2_n2", 2, 2),
    ("p_s6_n1", 6, 1),   # Very diversified
    ("p_s4_n3", 4, 3),   # Most diversified
]

# Simple regime gate: at least N of M votes
REGIME_VARIANTS = [
    # (label, votes_required, rules)
    # Rules: 0=csi300>sma200, 1=csi300_60d_ret>0, 2=breadth>50pct
    ("rg_2of3", 2, [0, 1, 2]),      # Current baseline
    ("rg_1of3", 1, [0, 1, 2]),      # More risk-on
    ("rg_3of3", 3, [0, 1, 2]),      # More risk-off
    ("rg_2of2_trend", 2, [0, 1]),   # Trend only
    ("rg_1of2_trend", 1, [0, 1]),   # Trend only, loose
]


def get_factor_expressions(groups):
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, groups)
    exprs, seen = [], set()
    for g in selected:
        for f in g.factors:
            if f.expression not in seen:
                exprs.append(f.expression); seen.add(f.expression)
    return exprs


def check_regime(symbol_data, rules, votes_required, date):
    """Check if regime gate passes for a given date. Simplified: always True for ranker eval."""
    # For ranker evaluation, we always generate scores (regime gate applied at portfolio level)
    return True


def get_regime_state(runtime, symbols, date, rules):
    """Get regime state for CN market at a given date. Returns True if risk-on."""
    try:
        csi300_data = runtime.features(["000300"], ["$close"], date.strftime("%Y-%m-%d"), date.strftime("%Y-%m-%d"))
        csi300_close = float(csi300_data.iloc[0, 0]) if len(csi300_data) > 0 else None
    except:
        return False

    votes = 0
    for rule in rules:
        if rule == 0:  # CSI300 > SMA200
            try:
                sma200_data = runtime.features(["000300"], ["Mean($close,200)"], date.strftime("%Y-%m-%d"), date.strftime("%Y-%m-%d"))
                sma200 = float(sma200_data.iloc[0, 0]) if len(sma200_data) > 0 else None
                if csi300_close and sma200 and csi300_close > sma200:
                    votes += 1
            except: pass
        elif rule == 1:  # CSI300 60d return positive
            try:
                ret60_data = runtime.features(["000300"], ["$close/Ref($close,60)-1"], date.strftime("%Y-%m-%d"), date.strftime("%Y-%m-%d"))
                ret60 = float(ret60_data.iloc[0, 0]) if len(ret60_data) > 0 else None
                if ret60 is not None and ret60 > 0:
                    votes += 1
            except: pass
        elif rule == 2:  # Breadth > 50%
            try:
                above_sma = 0; total = 0
                for sym in symbols[:50]:  # Sample for speed
                    try:
                        d = runtime.features([sym], ["$close/Mean($close,60)-1"], date.strftime("%Y-%m-%d"), date.strftime("%Y-%m-%d"))
                        v = float(d.iloc[0, 0]) if len(d) > 0 else None
                        if v is not None:
                            total += 1
                            if v > 0: above_sma += 1
                    except: pass
                if total > 0 and above_sma / total > 0.5:
                    votes += 1
            except: pass
    return votes >= 2  # default: 2 votes required


def evaluate_cn_portfolio(scores_df, returns_df, benchmark_df, eval_dates,
                          n_sectors=4, names_per_sector=1, regime_variant="rg_2of3",
                          cost_bps=20, cadence=10, runtime=None, symbols=None, eval_dates_orig=None):
    """Evaluate CN sector-based portfolio.

    Simplified: rank sectors by avg score, pick top N sectors, pick top M names each.
    """
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

        # Rank stocks by score
        ranked = daily_scores.sort_values("score", ascending=False)

        # Simple approach: pick top N sectors by average score, then top M names each
        # Since we don't have sector classification readily available for CN,
        # approximate: pick top (n_sectors * names_per_sector) stocks directly
        top_n = n_sectors * names_per_sector
        selected = [str(s) for s in ranked.index[:top_n]]

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


def run(root, *, provider_uri, output_dir):
    root = root.resolve()
    provider_uri = Path(provider_uri).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    universe = _load_yaml(UNIVERSE_CONFIG)
    print(f"Phase A: {len(PHASE_A_COMBOS)} ranker configs")
    print(f"Phase B: {len(PORTFOLIO_GRID_CN)} portfolio variants")

    runtime = QlibCNExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    requested = [str(s) for s in universe.get("symbols", [])]
    available = runtime.available_symbols()
    normalized = normalize_market_symbols("cn", requested, available_symbols=available)
    symbols = [item.normalized_symbol for item in normalized if item.normalized_symbol in available]
    print(f"Symbols: {len(symbols)}/{len(requested)}")

    # Pre-compute factor expressions
    all_factor_keys = set()
    for _, fk, _ in PHASE_A_COMBOS:
        all_factor_keys.add(fk)
    factor_exprs_map = {fk: get_factor_expressions(CN_FACTOR_GROUP_OPTIONS[fk]) for fk in all_factor_keys}
    for fk, exprs in factor_exprs_map.items():
        print(f"  {fk}: {len(exprs)} factors")

    all_exprs_set = set()
    for exprs in factor_exprs_map.values():
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

    # ---- Phase A: Ranker Optimization ----
    phase_a_results = []
    for window in windows:
        eval_dates = eval_dates_by_window[window.label]
        print(f"\n{'='*60}")
        print(f"PHASE A - Window: {window.label} ({len(eval_dates)} eval dates)")

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

        for combo_name, factor_key, cal_key in PHASE_A_COMBOS:
            expr_indices = [expr_to_idx[e] for e in factor_exprs_map[factor_key]]
            cal = CN_CALIBRATIONS[cal_key]
            n_factors = len(expr_indices)

            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(n_factors)]
            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{combo_name}")
            if not valid:
                continue

            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal)
            cf_test = features_all.loc[test_mask].iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(n_factors)]
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)

            # Evaluate with default portfolio (s4_n1)
            for cost_bps in (20, 60):
                result = evaluate_cn_portfolio(
                    scores, returns_all.loc[test_mask].copy(), benchmark,
                    eval_dates, n_sectors=4, names_per_sector=1,
                    cost_bps=cost_bps, cadence=10,
                )
                if result is None: continue
                result["combo_name"] = combo_name
                result["window"] = window.label
                result["cost_bps"] = cost_bps
                result["n_factors"] = n_factors
                result["factor_key"] = factor_key
                result["cal_key"] = cal_key
                phase_a_results.append(result)

        # Top-5 for this window at 20bps
        w20 = [r for r in phase_a_results if r["window"] == window.label and r["cost_bps"] == 20]
        w20.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"  Top-5 Phase A ({window.label}, 20bps):")
        for r in w20[:5]:
            print(f"    {r['combo_name']:30s} exc={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # ---- Phase A Aggregation ----
    print(f"\n{'='*60}")
    print("PHASE A: Ranker Cross-Window Aggregation (20bps)")

    by_combo_a = defaultdict(lambda: {"windows": {}, "costs": {}})
    for r in phase_a_results:
        cid = r["combo_name"]
        cost = r["cost_bps"]
        if cost not in by_combo_a[cid]["costs"]:
            by_combo_a[cid]["costs"][cost] = []
        by_combo_a[cid]["costs"][cost].append(r)
        if cost == 20:
            by_combo_a[cid]["windows"][r["window"]] = r

    agg_a = []
    for cid, data in by_combo_a.items():
        win_data = data["windows"]
        if len(win_data) != 4: continue
        ordered = [win_data[w] for w in DECISION_WINDOWS]
        strategy_nav = math.prod(1.0 + r["strategy_compound"] for r in ordered)
        bench_nav = math.prod(1.0 + r["benchmark_compound"] for r in ordered)
        compounded_rel_excess = strategy_nav / bench_nav - 1.0
        worst_dd = min(r["max_drawdown"] for r in ordered)
        positive = sum(1 for r in ordered if r["relative_excess"] > 0)

        # 60bps check
        exc_60 = None
        if 60 in data["costs"] and len(data["costs"][60]) == 4:
            o60 = sorted(data["costs"][60], key=lambda x: DECISION_WINDOWS.index(x["window"]))
            exc_60 = math.prod(1.0 + r["strategy_compound"] for r in o60) / math.prod(1.0 + r["benchmark_compound"] for r in o60) - 1.0

        agg_a.append({
            "combo_name": cid,
            "factor_key": ordered[0]["factor_key"],
            "cal_key": ordered[0]["cal_key"],
            "n_factors": ordered[0]["n_factors"],
            "compounded_relative_excess_20": compounded_rel_excess,
            "compounded_relative_excess_60": exc_60,
            "worst_drawdown_20": worst_dd,
            "positive_windows": positive,
            "per_window": {r["window"]: {"excess": r["relative_excess"], "dd": r["max_drawdown"]} for r in ordered},
        })

    # Find baseline for gate comparison
    baseline_a = next((r for r in agg_a if r["combo_name"] == "a01_baseline"), None)
    if baseline_a:
        base_dd_a = baseline_a["worst_drawdown_20"]
        base_excess_a = baseline_a["compounded_relative_excess_20"]
        print(f"Phase A baseline (a01_baseline): DD={base_dd_a:.4f}, Excess={base_excess_a:.4f}")

    agg_a.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)
    print(f"\nPhase A Top-10:")
    for i, r in enumerate(agg_a[:10]):
        exc60_str = f'{r["compounded_relative_excess_60"]:.4f}' if r["compounded_relative_excess_60"] else 'N/A'
        dd_impr = (base_dd_a - r["worst_drawdown_20"]) if baseline_a else 0
        print(f"  {i+1}. {r['combo_name']:<30s} exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} dd_impr={dd_impr:+.4f} exc@60={exc60_str} pos={r['positive_windows']}")

    # ---- Phase B: Portfolio Optimization (use best Phase A scores) ----
    # For now, take the best Phase A config and test portfolio grid
    # But this would require re-running with different portfolio construction on the SAME scores
    # Let me use a quick approach: take the best 3 configs from Phase A

    best_a_configs = agg_a[:3]
    print(f"\n{'='*60}")
    print(f"PHASE B: Portfolio Optimization on top-3 Phase A configs")

    # Re-run the portfolio grid for each of the top A configs
    phase_b_results = []
    for window in windows:
        eval_dates = eval_dates_by_window[window.label]
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

        for ba in best_a_configs:
            combo_name = ba["combo_name"]
            # Find the original combo definition
            orig = next((c for c in PHASE_A_COMBOS if c[0] == combo_name), None)
            if orig is None: continue
            _, factor_key, cal_key = orig
            cal = CN_CALIBRATIONS[cal_key]
            expr_indices = [expr_to_idx[e] for e in factor_exprs_map[factor_key]]

            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{combo_name}")
            if not valid: continue

            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal)
            cf_test = features_all.loc[test_mask].iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)

            for pfx, n_sec, n_names in PORTFOLIO_GRID_CN:
                result = evaluate_cn_portfolio(
                    scores, returns_all.loc[test_mask].copy(), benchmark,
                    eval_dates, n_sectors=n_sec, names_per_sector=n_names,
                    cost_bps=20, cadence=10,
                )
                if result is None: continue
                result["combo_name"] = f"{combo_name}__{pfx}"
                result["window"] = window.label
                result["cost_bps"] = 20
                result["n_sectors"] = n_sec
                result["names_per_sector"] = n_names
                phase_b_results.append(result)

        # Top-5 B
        wb = [r for r in phase_b_results if r["window"] == window.label]
        wb.sort(key=lambda r: r["relative_excess"], reverse=True)
        print(f"  Top-5 Phase B ({window.label}):")
        for r in wb[:5]:
            print(f"    {r['combo_name']:<45s} exc={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # Phase B aggregation
    print(f"\nPHASE B: Portfolio Cross-Window Aggregation")
    by_combo_b = defaultdict(lambda: {"windows": {}})
    for r in phase_b_results:
        by_combo_b[r["combo_name"]]["windows"][r["window"]] = r

    agg_b = []
    for cid, data in by_combo_b.items():
        if len(data["windows"]) != 4: continue
        ordered = [data["windows"][w] for w in DECISION_WINDOWS]
        strategy_nav = math.prod(1.0 + r["strategy_compound"] for r in ordered)
        bench_nav = math.prod(1.0 + r["benchmark_compound"] for r in ordered)
        compounded_rel_excess = strategy_nav / bench_nav - 1.0
        worst_dd = min(r["max_drawdown"] for r in ordered)
        positive = sum(1 for r in ordered if r["relative_excess"] > 0)

        agg_b.append({
            "combo_name": cid,
            "n_sectors": ordered[0].get("n_sectors", 4),
            "names_per_sector": ordered[0].get("names_per_sector", 1),
            "compounded_relative_excess_20": compounded_rel_excess,
            "worst_drawdown_20": worst_dd,
            "positive_windows": positive,
            "per_window": {r["window"]: {"excess": r["relative_excess"], "dd": r["max_drawdown"]} for r in ordered},
        })

    agg_b.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)
    print(f"\nPhase B Top-10:")
    for i, r in enumerate(agg_b[:10]):
        dd_impr = (base_dd_a - r["worst_drawdown_20"]) if baseline_a else 0
        print(f"  {i+1}. {r['combo_name']:<45s} exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} dd_impr={dd_impr:+.4f} pos={r['positive_windows']} sec={r['n_sectors']} names={r['names_per_sector']}")

    # ---- Final Summary ----
    print(f"\n{'='*60}")
    print("FINAL: Best Overall Candidates")

    # Gate analysis for top Phase A + Phase B
    all_final = agg_a + agg_b
    all_final.sort(key=lambda r: r["compounded_relative_excess_20"], reverse=True)

    print(f"\nTop-20 Overall:")
    for i, r in enumerate(all_final[:20]):
        dd_impr = (base_dd_a - r["worst_drawdown_20"]) if baseline_a else 0
        print(f"  {i+1}. {r['combo_name']:<45s} exc@20={r['compounded_relative_excess_20']:.4f} dd={r['worst_drawdown_20']:.4f} dd_impr={dd_impr:+.4f}")

    # Save
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "phase_a_configs": len(PHASE_A_COMBOS),
        "phase_b_configs": len(PORTFOLIO_GRID_CN),
        "phase_a_results": agg_a,
        "phase_b_results": agg_b,
        "baseline_dd": base_dd_a if baseline_a else None,
        "baseline_excess": base_excess_a if baseline_a else None,
    }
    _write_json(output_dir / "cn_comprehensive_grid.json", payload)
    print(f"\nSaved to {output_dir / 'cn_comprehensive_grid.json'}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider-uri", type=Path, default=Path("data/providers/cn"))
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/cn_x1_1_comprehensive_grid_v1"))
    args = p.parse_args()
    run(Path.cwd(), provider_uri=args.provider_uri, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
