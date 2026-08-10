"""USx integrated sector cap experiment: train models, apply sector caps, compare.

Tests whether the max-4-names-per-sector constraint improves drawdown
without destroying excess returns.
"""
from __future__ import annotations

import argparse, json, math, sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.daily_ranker import prepare_ranker_frame
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.notebook_experiment_api import run_10d_experiment
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
MAX_NAMES_PER_SECTOR = 4
TOP_N = 15
EXPERIMENT_ID = "us_x1_2_sector_cap_integrated_v1"


def _load_yaml(path): d = yaml.safe_load(Path(path).read_text(encoding="utf-8")); return d if isinstance(d, dict) else {}
def _write_json(path, payload): Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
def _compound(values): return math.prod(1.0 + v for v in values) - 1.0


def load_sectors():
    raw = _load_yaml(SECTOR_CONFIG)
    return {str(sym): str(rec["sector"]) for sym, rec in raw.get("records", {}).items()}


def select_capped(ranked_df, sector_map, top_n=15, max_per_sector=4):
    """Select top_n stocks respecting sector cap, fill from remaining if short."""
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


def compute_window_capped(scores_df, returns_df, sector_map, eval_dates, cost_bps=20):
    """Compute capped equal-weight portfolio returns for a window.

    Only evaluates at 10-session rebalance cadence to match uncapped evaluation.
    """
    # Take every 10th date (10-session rebalance cadence)
    cadence = 10
    rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]

    port_returns = []
    port_dates = []
    for date in rebalance_dates:
        try:
            daily_scores = scores_df.xs(date, level="datetime")
            daily_rets = returns_df.xs(date, level="datetime")
        except KeyError:
            continue
        daily_scores_df = daily_scores.reset_index()
        daily_scores_df.columns = ["instrument", "score"]
        selected = select_capped(daily_scores_df, sector_map, TOP_N, MAX_NAMES_PER_SECTOR)
        sel_rets = daily_rets[daily_rets.index.isin(selected)]
        if len(sel_rets) == 0:
            continue
        port_returns.append(float(sel_rets["return"].mean()))
        port_dates.append(date)

    if not port_returns:
        return None
    return pd.Series(port_returns, index=pd.DatetimeIndex(port_dates), name="capped_return")


def _get_factor_expressions(groups):
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, groups)
    exprs, seen = [], set()
    for g in selected:
        for f in g.factors:
            if f.expression not in seen:
                exprs.append(f.expression); seen.add(f.expression)
    return exprs


def run(root, *, provider_uri, output_dir):
    root = root.resolve()
    provider_uri = Path(provider_uri).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model = _load_yaml(MODEL_CONFIG)
    universe = _load_yaml(UNIVERSE_CONFIG)
    sector_map = load_sectors()
    print(f"[sector_cap] {len(sector_map)} sector mappings loaded")

    # Standard calibration
    std_cal = XGBNativeCalibration.from_dict({
        "n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
        "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
        "subsample": 1.0, "colsample_bytree": 1.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42,
    })
    best_cal = XGBNativeCalibration.from_dict({
        "n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
        "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
        "subsample": 0.8, "colsample_bytree": 0.8, "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42,
    })

    # Test: baseline (std cal) + best challenger (best cal, +risk_ctrl factors)
    candidates_def = [
        ("baseline_std", ["momentum_volatility_volume"], std_cal),
        ("challenger_best", ["momentum_volatility_volume", "risk_controlled_momentum"], best_cal),
    ]
    candidate_exprs = {cid: _get_factor_expressions(grps) for cid, grps, _ in candidates_def}

    all_exprs_set = set()
    for exprs in candidate_exprs.values():
        all_exprs_set.update(exprs)
    all_exprs = sorted(all_exprs_set)
    expr_to_idx = {e: i for i, e in enumerate(all_exprs)}

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)

    # Resolve symbols
    requested = [str(s) for s in universe.get("symbols", [])]
    available = runtime.available_symbols()
    normalized = normalize_market_symbols("us", requested, available_symbols=available)
    symbols = [item.normalized_symbol for item in normalized]
    print(f"[sector_cap] {len(symbols)} symbols")

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
        print(f"\n[sector_cap] === {window.label} ({len(eval_dates)} eval dates) ===")

        # Load features and returns
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
        returns_test.attrs.update(returns_all.attrs)

        benchmark = load_window_benchmark_returns(
            runtime, benchmark_instrument="QQQ", return_expression=RETURN_EXPRESSION,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        for cid, groups, cal in candidates_def:
            expr_indices = [expr_to_idx[e] for e in candidate_exprs[cid]]
            cf_all = features_all.iloc[:, expr_indices].copy()
            cf_all.columns = [f"feature_{i}" for i in range(len(expr_indices))]

            cf_train = cf_all.loc[train_mask].copy()
            ret_train = returns_all.loc[train_mask].copy()
            cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)
            valid, reason = validate_no_nan_inputs(cf_train, context=f"{window.label}/{cid}")
            if not valid:
                raise ValueError(reason)

            x_rank, y_rank, groups_arr = prepare_ranker_frame(cf_train, ret_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups_arr, calibration=cal)
            cf_test = features_test.iloc[:, expr_indices].copy()
            cf_test.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            scores = predict_xgb_native_daily_ranker(fitted, cf_test)

            # Uncapped evaluation
            cand_name = f"xgb:{'+'.join(groups)}:native:{cid}"
            context = SpecBoundEvaluationContext(
                market="us", symbols=tuple(symbols), benchmark="QQQ",
                train_start=window.train_start, train_end=window.train_end,
                test_start=eval_dates.min().strftime("%Y-%m-%d"),
                test_end=eval_dates.max().strftime("%Y-%m-%d"),
                holding_days=10, rebalance_days=10, topk=15,
                model_type="sector_cap", factor_expressions=tuple(candidate_exprs[cid]),
                return_expression=RETURN_EXPRESSION,
                experiment_id=f"{EXPERIMENT_ID}_{window.label}_{cid}",
            )
            report = run_10d_experiment(
                config=context, candidates={cand_name: scores},
                raw_returns=returns_test, benchmark_returns=benchmark,
                output_dir=output_dir / "reports",
            )
            comp = report.get("comparison_report", {})
            orig_cands = comp.get("candidates", [])
            orig = orig_cands[0] if orig_cands else {}

            # Capped evaluation
            capped_returns = compute_window_capped(scores, returns_test, sector_map, eval_dates)
            if capped_returns is not None and len(capped_returns) > 0:
                # Use exact same evaluation dates as capped returns
                common = capped_returns.index.intersection(benchmark.index)
                cap_aligned = capped_returns[common]
                bench_aligned = benchmark.loc[common, "return"]

                cap_compound = _compound([float(r) for r in cap_aligned])
                bench_compound = _compound([float(r) for r in bench_aligned])
                cap_relative = (1.0 + cap_compound) / (1.0 + bench_compound) - 1.0

                # DD
                cum = (1.0 + cap_aligned).cumprod()
                running_max = cum.cummax()
                cap_dd = float(((cum - running_max) / running_max).min())

                # Uncapped for comparison
                uncapped_total = float(orig.get("total_return", 0))
                uncapped_bench = float(orig.get("benchmark_return", 0))
                uncapped_dd = float(orig.get("max_drawdown", 0))
                uncapped_excess = uncapped_total - uncapped_bench

                # Uncapped relative excess for fair comparison
                uncapped_relative = (1.0 + uncapped_total) / (1.0 + uncapped_bench) - 1.0 if uncapped_bench > -1 else 0

                dd_improve = uncapped_dd - cap_dd
                excess_change = cap_relative - uncapped_relative

                row = {
                    "window": window.label, "candidate": cid,
                    "uncapped_relative_excess": float(uncapped_relative),
                    "capped_relative_excess": float(cap_relative),
                    "uncapped_dd": float(uncapped_dd),
                    "capped_dd": float(cap_dd),
                    "dd_improvement": float(dd_improve),
                    "excess_change": float(excess_change),
                }
                all_results.append(row)

                print(f"  {cid}: uncapped rel_excess={uncapped_relative:.4f} dd={uncapped_dd:.4f} -> "
                      f"capped rel_excess={cap_relative:.4f} dd={cap_dd:.4f} "
                      f"(dd_improve={dd_improve:+.4f}, excess_change={excess_change:+.4f})")

    # Summary
    print("\n[sector_cap] === SUMMARY ===")
    by_cand = {}
    for r in all_results:
        by_cand.setdefault(r["candidate"], []).append(r)
    for cand, rows in by_cand.items():
        avg_dd = np.mean([r["dd_improvement"] for r in rows])
        avg_excess_change = np.mean([r["excess_change"] for r in rows])
        total_rel_uncapped = sum(r["uncapped_relative_excess"] for r in rows)
        total_rel_capped = sum(r["capped_relative_excess"] for r in rows)
        print(f"  {cand}: avg_dd_improve={avg_dd:+.4f}, avg_excess_change={avg_excess_change:+.4f}, "
              f"sum_rel_uncapped={total_rel_uncapped:.4f}, sum_rel_capped={total_rel_capped:.4f}")

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "max_names_per_sector": MAX_NAMES_PER_SECTOR,
        "top_n": TOP_N,
        "windows": list(DECISION_WINDOWS),
        "results": all_results,
        "summary": {
            cand: {
                "avg_dd_improvement": float(np.mean([r["dd_improvement"] for r in rows])),
                "avg_excess_change": float(np.mean([r["excess_change"] for r in rows])),
                "sum_uncapped_relative_excess": float(sum(r["uncapped_relative_excess"] for r in rows)),
                "sum_capped_relative_excess": float(sum(r["capped_relative_excess"] for r in rows)),
            }
            for cand, rows in by_cand.items()
        },
    }
    _write_json(output_dir / "sector_cap_integrated.json", payload)
    print(f"\n[sector_cap] saved to {output_dir / 'sector_cap_integrated.json'}")
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider-uri", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/us_x1_2_sector_cap_integrated_v1"))
    args = p.parse_args()
    payload = run(Path.cwd(), provider_uri=args.provider_uri, output_dir=args.output_dir)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
