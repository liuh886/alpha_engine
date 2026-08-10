"""USx multi-dimensional grid: test Top-K, sector cap, bins, calibration, factors.

Trains models once per config, then applies portfolio construction grid to same scores.
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
from src.research.evaluation_context import SpecBoundEvaluationContext
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
MODEL_CONFIG = Path("configs/models/us_x1_1.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/us_selected_equities_v2.yaml")
DECISION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
EXPERIMENT_ID = "us_x1_2_multidim_grid_v1"

# ---- helpers ----
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
        if counts.get(sec, 0) >= max_per_sector:
            continue
        selected.append(sym)
        counts[sec] = counts.get(sec, 0) + 1
        if len(selected) >= top_n:
            break
    if len(selected) < top_n:
        for _, row in ranked.iterrows():
            sym = str(row["instrument"])
            if sym not in selected:
                selected.append(sym)
            if len(selected) >= top_n:
                break
    return selected[:top_n]


def evaluate_portfolio(scores_df, returns_df, benchmark_df, sector_map, eval_dates,
                       top_n=15, max_per_sector=None, cadence=10):
    """Evaluate portfolio with given construction params. Returns dict of metrics."""
    rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
    port_returns, port_dates = [], []

    for date in rebalance_dates:
        try:
            daily_scores = scores_df.xs(date, level="datetime")
            daily_rets = returns_df.xs(date, level="datetime")
        except KeyError:
            continue

        daily_scores_df = daily_scores.reset_index()
        daily_scores_df.columns = ["instrument", "score"]

        if max_per_sector is not None:
            selected = select_capped(daily_scores_df, sector_map, top_n, max_per_sector)
        else:
            ranked = daily_scores_df.sort_values("score", ascending=False)
            selected = [str(s) for s in ranked["instrument"].iloc[:top_n]]

        sel_rets = daily_rets[daily_rets.index.isin(selected)]
        if len(sel_rets) == 0:
            continue
        port_returns.append(float(sel_rets["return"].mean()))
        port_dates.append(date)

    if not port_returns:
        return None

    port_series = pd.Series(port_returns, index=pd.DatetimeIndex(port_dates))
    common = port_series.index.intersection(benchmark_df.index)
    port_aligned = port_series[common]
    bench_aligned = benchmark_df.loc[common, "return"]

    strategy_compound = _compound([float(r) for r in port_aligned])
    benchmark_compound = _compound([float(r) for r in bench_aligned])
    relative_excess = (1.0 + strategy_compound) / (1.0 + benchmark_compound) - 1.0

    cum = (1.0 + port_aligned).cumprod()
    running_max = cum.cummax()
    max_dd = float(((cum - running_max) / running_max).min())

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


# ---- model configs to test ----
MODEL_CONFIGS = [
    # (model_id, factor_groups, n_gain_bins, calibration)
    ("m_7f_b7_std", ["momentum_volatility_volume"], 7,
     XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,
         "max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,
         "subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("m_7f_b5_std", ["momentum_volatility_volume"], 5,
     XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":200,"max_leaves":31,
         "max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,
         "subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("m_7f_b7_sampled", ["momentum_volatility_volume"], 7,
     XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,
         "max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,
         "subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("m_9f_b7_std", ["momentum_volatility_volume","risk_controlled_momentum"], 7,
     XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,
         "max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,
         "subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
    ("m_9f_b7_sampled", ["momentum_volatility_volume","risk_controlled_momentum"], 7,
     XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,
         "max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,
         "subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})),
]

# ---- portfolio construction grid ----
PORTFOLIO_GRID = [
    # (label_suffix, top_n, max_per_sector)
    ("t15_s4", 15, 4),    # baseline from R3
    ("t10_s3", 10, 3),    # tighter concentration
    ("t10_s4", 10, 4),
    ("t10_s5", 10, 5),
    ("t12_s3", 12, 3),
    ("t12_s4", 12, 4),
    ("t12_s5", 12, 5),
    ("t15_s3", 15, 3),    # tighter sector cap
    ("t15_s5", 15, 5),    # looser sector cap
    ("t20_s3", 20, 3),
    ("t20_s4", 20, 4),
    ("t20_s5", 20, 5),
    ("t15_nosec", 15, None),  # no sector cap - pure baseline
    ("t10_nosec", 10, None),
    ("t20_nosec", 20, None),
]


def run(root, *, provider_uri, output_dir):
    root = root.resolve()
    provider_uri = Path(provider_uri).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model_data = _load_yaml(MODEL_CONFIG)
    universe = _load_yaml(UNIVERSE_CONFIG)
    sector_map = load_sectors()
    print(f"Models: {len(MODEL_CONFIGS)}, Portfolio variants: {len(PORTFOLIO_GRID)}")
    print(f"Total evaluations per window: {len(MODEL_CONFIGS) * len(PORTFOLIO_GRID)}")

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

    # Pre-compute factor expressions
    model_exprs = {}
    for mid, groups, bins, cal in MODEL_CONFIGS:
        if mid not in model_exprs:
            model_exprs[mid] = _get_factor_expressions(groups)

    all_exprs_set = set()
    for exprs in model_exprs.values():
        all_exprs_set.update(exprs)
    all_exprs = sorted(all_exprs_set)
    expr_to_idx = {e: i for i, e in enumerate(all_exprs)}

    # Results: window -> model -> portfolio -> metrics
    window_results: dict[str, list[dict]] = defaultdict(list)
    all_portfolio_results: list[dict] = []

    for window in windows:
        eval_dates = eval_dates_by_window[window.label]
        print(f"\n{'='*60}")
        print(f"Window: {window.label} | Train: {window.train_start}..{window.train_end} | Eval dates: {len(eval_dates)}")

        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, all_exprs, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{i}" for i in range(len(all_exprs))]

        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        )
        returns_all.columns = ["return"]
        returns_all.attrs.update({"provenance": "raw_forward_return", "horizon": 10})

        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = dates.isin(eval_dates)
        features_test = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()

        benchmark = load_window_benchmark_returns(
            runtime, benchmark_instrument="QQQ", return_expression=RETURN_EXPRESSION,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        # Train each model and compute scores
        model_scores = {}
        for mid, groups, bins, cal in MODEL_CONFIGS:
            expr_indices = [expr_to_idx[e] for e in model_exprs[mid]]
            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{mid}")
            if not valid:
                raise ValueError(reason)
            # Override n_gain_bins in calibration
            cal_bins = XGBNativeCalibration.from_dict({
                **{k:v for k,v in cal.__dict__.items() if not k.startswith('_')},
                "n_gain_bins": bins,
            })
            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal_bins)
            cf_test = features_test.iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            model_scores[mid] = predict_xgb_native_daily_ranker(fitted, cf_test)
            print(f"  Model {mid}: trained ({len(expr_indices)} features, {bins} bins)")

        # Evaluate all model × portfolio combinations
        for mid in model_scores:
            scores = model_scores[mid]
            for pfx, top_n, max_sec in PORTFOLIO_GRID:
                result = evaluate_portfolio(
                    scores, returns_test, benchmark, sector_map,
                    eval_dates, top_n=top_n, max_per_sector=max_sec, cadence=10
                )
                if result is None:
                    continue
                combo_id = f"{mid}__{pfx}"
                result["combo_id"] = combo_id
                result["window"] = window.label
                result["model_id"] = mid
                result["portfolio"] = pfx
                result["top_n"] = top_n
                result["max_per_sector"] = max_sec
                window_results[window.label].append(result)
                all_portfolio_results.append(result)

        # Print top-5 for this window
        sorted_results = sorted(
            [r for r in window_results[window.label]],
            key=lambda r: r["relative_excess"], reverse=True
        )
        print(f"  Top-5 this window (by relative excess):")
        for r in sorted_results[:5]:
            print(f"    {r['combo_id']:40s} excess={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # ---- Cross-window aggregation ----
    print(f"\n{'='*60}")
    print("CROSS-WINDOW AGGREGATION")

    by_combo = defaultdict(lambda: {"windows": {}, "rel_excesses": [], "dds": []})
    for r in all_portfolio_results:
        cid = r["combo_id"]
        by_combo[cid]["windows"][r["window"]] = r
        by_combo[cid]["rel_excesses"].append(r["relative_excess"])
        by_combo[cid]["dds"].append(r["max_drawdown"])

    # Compute compound across windows
    aggregated = []
    for cid, data in by_combo.items():
        if len(data["windows"]) != 4:
            continue
        ordered = [data["windows"][w] for w in DECISION_WINDOWS]
        strategy_nav = math.prod(1.0 + r["strategy_compound"] for r in ordered)
        bench_nav = math.prod(1.0 + r["benchmark_compound"] for r in ordered)
        compounded_rel_excess = strategy_nav / bench_nav - 1.0
        worst_dd = min(r["max_drawdown"] for r in ordered)
        positive = sum(1 for r in ordered if r["relative_excess"] > 0)
        strongest = max(r["relative_excess"] for r in ordered) / sum(
            r["relative_excess"] for r in ordered if r["relative_excess"] > 0
        ) if sum(r["relative_excess"] for r in ordered if r["relative_excess"] > 0) > 0 else 1.0

        aggregated.append({
            "combo_id": cid,
            "model_id": ordered[0]["model_id"],
            "portfolio": ordered[0]["portfolio"],
            "top_n": ordered[0]["top_n"],
            "max_per_sector": ordered[0]["max_per_sector"],
            "compounded_relative_excess": compounded_rel_excess,
            "worst_drawdown": worst_dd,
            "positive_windows": positive,
            "strongest_share": strongest,
            "per_window": {r["window"]: {"excess": r["relative_excess"], "dd": r["max_drawdown"]} for r in ordered},
        })

    # Sort by selection score (same formula as native grid: excess - 1.5*penalty + ...)
    def selection_score(r):
        dd_penalty = max(0.0, -r["worst_drawdown"] - 0.22)
        return r["compounded_relative_excess"] - 1.5 * dd_penalty + 0.15 * r["strongest_share"]

    aggregated.sort(key=selection_score, reverse=True)

    print(f"\nTop-20 combinations (by selection score):")
    print(f"{'Rank':<5} {'Combo':<45s} {'Excess':>8s} {'WorstDD':>8s} {'PosWin':>6s} {'Strong%':>7s} {'TopN':>5s} {'SecCap':>6s}")
    print("-" * 135)
    for i, r in enumerate(aggregated[:20]):
        print(f"{i+1:<5} {r['combo_id']:<45s} {r['compounded_relative_excess']:>8.4f} {r['worst_drawdown']:>8.4f} {r['positive_windows']:>6} {r['strongest_share']:>7.4f} {r['top_n']:>5} {str(r['max_per_sector']):>6s}")

    # Gate analysis for top candidates
    print(f"\nGate analysis for top-5:")
    for r in aggregated[:5]:
        # Use baseline uncapped (model m_7f_b7_std, t15_nosec) for comparison
        baseline = next((x for x in aggregated if x["combo_id"] == "m_7f_b7_std__t15_nosec"), None)
        if baseline:
            dd_gate = r["worst_drawdown"] >= baseline["worst_drawdown"] + 0.03 or r["worst_drawdown"] >= -0.22
            excess_gate = r["compounded_relative_excess"] >= 0.90 * baseline["compounded_relative_excess"]
        else:
            dd_gate = r["worst_drawdown"] >= -0.22
            excess_gate = True
        gates = {
            "DD_improve_3pp_or_above_m22": dd_gate,
            "4_positive_windows": r["positive_windows"] == 4,
            "strongest_share_below_55pct": r["strongest_share"] < 0.55,
            "retain_90pct_baseline_excess": excess_gate,
        }
        all_pass = all(gates.values())
        print(f"  {r['combo_id']}: all_pass={all_pass}")
        for g, v in gates.items():
            print(f"    {g}: {'PASS' if v else 'FAIL'}")

    # Per-window detail for top-3
    print(f"\nPer-window detail for top-3:")
    for r in aggregated[:3]:
        print(f"\n  {r['combo_id']} (excess={r['compounded_relative_excess']:.4f}, dd={r['worst_drawdown']:.4f}):")
        for w in DECISION_WINDOWS:
            pw = r["per_window"].get(w, {})
            print(f"    {w}: excess={pw.get('excess',0):.4f}, dd={pw.get('dd',0):.4f}")

    # Save results
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "models_tested": len(MODEL_CONFIGS),
        "portfolio_variants": len(PORTFOLIO_GRID),
        "total_evaluations": len(all_portfolio_results),
        "top_results": aggregated[:30],
        "all_results": aggregated,
    }
    _write_json(output_dir / "multidim_grid.json", payload)
    print(f"\nSaved to {output_dir / 'multidim_grid.json'}")
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider-uri", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/us_x1_2_multidim_grid_v1"))
    args = p.parse_args()
    payload = run(Path.cwd(), provider_uri=args.provider_uri, output_dir=args.output_dir)
    print(json.dumps({"top_combo": payload["top_results"][0]["combo_id"] if payload["top_results"] else "none"}))


if __name__ == "__main__":
    main()
