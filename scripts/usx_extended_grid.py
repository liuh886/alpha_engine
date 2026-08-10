"""USx extended experiment: combine factor group expansion with XGB calibration.

Tests factor_group × calibration combinations against the frozen US x1.1
baseline across 2024H1--2025H2.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

# Use the native grid infrastructure
from scripts.run_us_x1_1_native_xgb_grid import (
    _load_yaml,
    _write_json,
    _compound,
    _candidate_name,
    _original_result,
    _stress_result,
    _score_diagnostics,
    _resolve_symbols as grid_resolve_symbols,
    DECISION_WINDOWS,
    COST_STRESS_BPS,
    BASELINE_ID,
    RETURN_EXPRESSION,
    EXPERIMENT_CONFIG,
    MODEL_CONFIG,
    UNIVERSE_CONFIG,
    EXPERIMENT_ID,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.walk_forward_stability import summarize_walk_forward_reports
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

FACTOR_LIBRARY_PATH = Path("configs/factor_libraries/ohlcv.yaml")
EXTENDED_ID = "us_x1_2_extended_grid_v1"


def _resolve_universe_symbols(runtime, universe):
    """Resolve symbols robustly (patched from grid runner)."""
    requested = [str(item) for item in universe.get("symbols", [])]
    available = runtime.available_symbols()
    normalized = normalize_market_symbols("us", requested, available_symbols=available)
    resolved = [item.normalized_symbol for item in normalized]
    missing = sorted(set(requested) - set(resolved))
    if missing:
        print(f"[extended] WARNING: missing {len(missing)} symbols: {missing[:5]}...")
    if len(resolved) < 30:
        raise ValueError(f"only {len(resolved)} symbols — insufficient")
    return resolved


def _get_factor_expressions(groups: list[str]) -> list[str]:
    """Get Qlib expressions for factor groups from the OHLCV library."""
    library = load_factor_library(FACTOR_LIBRARY_PATH)
    selected = select_factor_groups(library, groups)
    expressions: list[str] = []
    seen: set[str] = set()
    for g in selected:
        for f in g.factors:
            if f.expression not in seen:
                expressions.append(f.expression)
                seen.add(f.expression)
    return expressions


def _aggregate_extended(cal_id, candidate_name, manifest, window_rows):
    """Aggregate window results for one candidate (same logic as native grid)."""
    ordered = sorted(window_rows, key=lambda item: DECISION_WINDOWS.index(item["window"]))
    aggregates: dict[str, Any] = {}
    for cost in COST_STRESS_BPS:
        rows = [dict(item["cost_stress"][str(cost)]) for item in ordered]
        strategy = _compound([float(row["total_return"]) for row in rows])
        benchmark = _compound([float(row["benchmark_return"]) for row in rows])
        aggregates[str(cost)] = {
            "compounded_strategy_return": strategy,
            "compounded_benchmark_return": benchmark,
            "compounded_relative_excess_return": (1.0 + strategy) / (1.0 + benchmark) - 1.0,
        }
    base_rows = [dict(item["cost_stress"]["20"]) for item in ordered]
    simple_excess = [float(row["excess_return"]) for row in base_rows]
    positive = [v for v in simple_excess if v > 0]
    recurring = set(str(item) for item in base_rows[0].get("top_selected_stocks", []))
    for row in base_rows[1:]:
        recurring &= set(str(item) for item in row.get("top_selected_stocks", []))
    strongest_share = max(positive) / sum(positive) if positive and sum(positive) > 0 else 1.0
    return {
        "calibration_id": cal_id,
        "candidate_name": candidate_name,
        "parameter_identity": manifest,
        "n_windows": len(ordered),
        "positive_excess_windows": sum(v > 0 for v in simple_excess),
        "mean_icir": float(np.mean([float(row["icir"]) for row in base_rows])),
        "mean_rank_ic": float(np.mean([float(row["rank_ic"]) for row in base_rows])),
        "mean_spread": float(np.mean([
            float(row["score_direction"]["top_minus_bottom_spread"]) for row in base_rows
        ])),
        "worst_drawdown": min(float(row["max_drawdown"]) for row in base_rows),
        "strongest_positive_window_share": float(strongest_share),
        "all_window_recurring_names": sorted(recurring),
        "cost_stress": aggregates,
        "windows": ordered,
    }


def _decision_extended(aggregates, baseline_id, provider_ok, deterministic_baseline):
    """Make extended decision comparing all candidates to baseline."""
    by_id = {str(item["calibration_id"]): item for item in aggregates}
    baseline = by_id[baseline_id]
    baseline_rel = float(baseline["cost_stress"]["20"]["compounded_relative_excess_return"])
    baseline_dd = float(baseline["worst_drawdown"])
    baseline_ic = float(baseline["mean_rank_ic"])

    evaluated = []
    for row in aggregates:
        if row["calibration_id"] == baseline_id:
            continue
        rel20 = float(row["cost_stress"]["20"]["compounded_relative_excess_return"])
        rel60 = float(row["cost_stress"]["60"]["compounded_relative_excess_return"])
        gates = {
            "four_positive_excess_windows": int(row["positive_excess_windows"]) == 4,
            "positive_60_bps_relative_excess": rel60 > 0,
            "retain_at_least_90pct_baseline_relative_excess": rel20 >= 0.90 * baseline_rel,
            "drawdown_improves_3pp_or_stays_above_minus_22pct": (
                float(row["worst_drawdown"]) >= baseline_dd + 0.03
                or float(row["worst_drawdown"]) >= -0.22
            ),
            "mean_rank_ic_not_materially_weaker": (
                float(row["mean_rank_ic"]) >= max(0.0, baseline_ic - 0.005)
            ),
            "strongest_window_share_below_55pct": (
                float(row["strongest_positive_window_share"]) < 0.55
            ),
        }
        penalty = max(0.0, -float(row["worst_drawdown"]) - 0.22)
        selection_score = (
            rel20 - 1.5 * penalty + 0.15 * float(row["mean_icir"])
            + 0.10 * float(row["mean_rank_ic"])
            + 0.10 * (1.0 - float(row["strongest_positive_window_share"]))
        )
        evaluated.append({
            "calibration_id": row["calibration_id"],
            "gates": gates,
            "all_gates_pass": all(gates.values()),
            "selection_score": selection_score,
        })

    supported = sorted(
        [e for e in evaluated if e["all_gates_pass"]],
        key=lambda e: float(e["selection_score"]),
        reverse=True,
    )
    if not provider_ok:
        decision = "data_blocked"
        selected = None
    elif not deterministic_baseline:
        decision = "extended_grid_unstable"
        selected = None
    elif supported:
        decision = "extended_x1_2_candidate_supported"
        selected = supported[0]["calibration_id"]
    else:
        decision = "no_candidate_passes_all_gates"
        selected = None
    return {
        "decision": decision,
        "selected_calibration_id": selected,
        "provider_matches_canonical": provider_ok,
        "deterministic_baseline": deterministic_baseline,
        "candidate_gate_results": evaluated,
        "automatic_model_update": False,
        "may_create_us_x1_2_candidate": decision == "extended_x1_2_candidate_supported",
        "new_untouched_challenge_required": True,
    }


def run(root: Path, *, provider_uri: Path, output_dir: Path) -> dict[str, Any]:
    root = root.resolve()
    provider_uri = provider_uri.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    experiment = _load_yaml(root / EXPERIMENT_CONFIG)
    model = _load_yaml(root / MODEL_CONFIG)
    universe = _load_yaml(root / UNIVERSE_CONFIG)

    # Best calibration from round 1
    best_cal = XGBNativeCalibration.from_dict({
        "n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
        "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
        "subsample": 0.8, "colsample_bytree": 0.8,
        "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42,
    })

    # Standard calibration (baseline)
    std_cal = XGBNativeCalibration.from_dict({
        "n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
        "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
        "subsample": 1.0, "colsample_bytree": 1.0,
        "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42,
    })

    # Define candidates: (calibration_id, factor_groups, calibration)
    candidates_def: list[tuple[str, list[str], XGBNativeCalibration]] = [
        ("baseline_7factor_std", ["momentum_volatility_volume"], std_cal),
        ("baseline_7factor_sampled", ["momentum_volatility_volume"], best_cal),
        ("risk_ctrl_9factor_sampled", ["momentum_volatility_volume", "risk_controlled_momentum"], best_cal),
    ]

    # Pre-compute factor expressions per candidate
    candidate_exprs = {
        cid: _get_factor_expressions(groups)
        for cid, groups, _ in candidates_def
    }
    for cid, exprs in candidate_exprs.items():
        print(f"[extended] {cid}: {len(exprs)} factors: {exprs}")

    canonical_provider = str(model["provider_binding"]["canonical_evidence_provider_identity_sha256"])

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    runtime_meta = runtime.metadata()
    observed_provider = str(runtime_meta.get("provider_identity_sha256", ""))

    symbols = _resolve_universe_symbols(runtime, universe)
    print(f"[extended] using {len(symbols)} symbols")

    calendar = runtime.calendar("2021-01-01", "2025-12-31")
    available_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar, "2021-01-01", available_end,
        first_test_year=2024, last_test_year=2025, min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10, cadence_sessions=10,
    )
    windows = list(window_plan.selected_windows)
    if tuple(w.label for w in windows) != DECISION_WINDOWS:
        raise ValueError(f"unexpected windows: {[w.label for w in windows]}")
    evaluation_dates_by_window = horizon_eligible_dates_by_window(window_plan, calendar)

    manifests = {cid: cal.identity_manifest() for cid, _, cal in candidates_def}
    window_rows_by_candidate: dict[str, list[dict[str, Any]]] = {
        cid: [] for cid, _, _ in candidates_def
    }
    reports = []
    deterministic_checks = []

    baseline_cid = candidates_def[0][0]  # baseline_7factor_std

    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        print(f"[extended] window={window.label} train={window.train_start}..{window.train_end} test_n={len(evaluation_dates)}")

        # Load ALL possible features needed across candidates
        all_exprs_set: set[str] = set()
        for exprs in candidate_exprs.values():
            all_exprs_set.update(exprs)
        all_exprs = sorted(all_exprs_set)
        expr_to_idx = {e: i for i, e in enumerate(all_exprs)}

        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, all_exprs, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{i}" for i in range(len(all_exprs))]

        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        )
        returns_all.columns = ["return"]
        returns_all.attrs.update({"provenance": "raw_forward_return", "horizon": 10, "expression": RETURN_EXPRESSION})

        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = dates.isin(evaluation_dates)

        features_test = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)

        scores_by_cid: dict[str, pd.DataFrame] = {}
        for cid, factor_groups, calibration in candidates_def:
            expr_indices = [expr_to_idx[e] for e in candidate_exprs[cid]]
            cand_features_all = features_all.iloc[:, expr_indices].copy()
            cand_features_all.columns = [f"feature_{i}" for i in range(len(expr_indices))]

            features_train_raw = cand_features_all.loc[train_mask].copy()
            returns_train_raw = returns_all.loc[train_mask].copy()
            features_train, returns_train = purge_training_tail(
                features_train_raw, returns_train_raw, holding_days=10
            )
            valid, reason = validate_no_nan_inputs(features_train, context=f"train/{window.label}/{cid}")
            if not valid:
                raise ValueError(reason)

            x_rank, y_rank, groups = prepare_ranker_frame(features_train, returns_train)
            fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups, calibration=calibration)
            cand_features_test = features_test.iloc[:, expr_indices].copy()
            cand_features_test.columns = [f"feature_{i}" for i in range(len(expr_indices))]
            scores_by_cid[cid] = predict_xgb_native_daily_ranker(fitted, cand_features_test)

        # Deterministic check for baseline
        baseline_scores = scores_by_cid[baseline_cid]
        baseline_groups, baseline_cal = candidates_def[0][1], candidates_def[0][2]
        expr_indices_bl = [expr_to_idx[e] for e in candidate_exprs[baseline_cid]]
        ft_bl = features_all.loc[train_mask].iloc[:, expr_indices_bl].copy()
        ft_bl.columns = [f"feature_{i}" for i in range(len(expr_indices_bl))]
        rt_bl = returns_all.loc[train_mask].copy()
        ft_bl, rt_bl = purge_training_tail(ft_bl, rt_bl, holding_days=10)
        x_r2, y_r2, g_r2 = prepare_ranker_frame(ft_bl, rt_bl)
        rep = fit_xgb_native_daily_ranker(x_r2, y_r2, g_r2, calibration=baseline_cal)
        ft_test_bl = features_test.iloc[:, expr_indices_bl].copy()
        ft_test_bl.columns = [f"feature_{i}" for i in range(len(expr_indices_bl))]
        rep_scores = predict_xgb_native_daily_ranker(rep, ft_test_bl)
        deterministic_checks.append(bool(np.allclose(
            baseline_scores["score"].to_numpy(), rep_scores["score"].to_numpy(), rtol=0.0, atol=1e-12
        )))

        benchmark = load_window_benchmark_returns(
            runtime, benchmark_instrument="QQQ", return_expression=RETURN_EXPRESSION,
            evaluation_dates=evaluation_dates,
            start=evaluation_dates.min().strftime("%Y-%m-%d"),
            end=evaluation_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        context = SpecBoundEvaluationContext(
            market="us", symbols=tuple(symbols), benchmark="QQQ",
            train_start=window.train_start, train_end=window.train_end,
            test_start=evaluation_dates.min().strftime("%Y-%m-%d"),
            test_end=evaluation_dates.max().strftime("%Y-%m-%d"),
            holding_days=10, rebalance_days=10, topk=15,
            model_type="us_x1_2_extended_grid",
            factor_expressions=tuple(all_exprs),
            return_expression=RETURN_EXPRESSION,
            experiment_id=f"{EXTENDED_ID}_{window.label}",
        )

        # Build named scores with descriptive names
        named_scores = {}
        for cid, groups, cal in candidates_def:
            name = f"xgb:daily_ranker:{'+'.join(groups)}:native:{cid}"
            named_scores[name] = scores_by_cid[cid]

        report = run_10d_experiment(
            config=context, candidates=named_scores,
            raw_returns=returns_test, benchmark_returns=benchmark,
            output_dir=output_dir / "windows",
        )
        report["provider_identity_sha256"] = observed_provider
        reports.append(report)
        if report.get("artifact_path"):
            _write_json(Path(str(report["artifact_path"])),
                        {k: v for k, v in report.items() if k != "artifact_path"})

        # Collect per-candidate per-window results
        for cid, groups, cal in candidates_def:
            cand_name = f"xgb:daily_ranker:{'+'.join(groups)}:native:{cid}"
            cost_stress = {"20": _original_result(report, cand_name)}
            for cost in (40, 60):
                cost_stress[str(cost)] = _stress_result(
                    scores_by_cid[cid], returns_test, benchmark, cost_bps=cost
                )
            diag = _score_diagnostics(baseline_scores, scores_by_cid[cid])
            window_rows_by_candidate[cid].append({
                "window": window.label, "train_start": window.train_start,
                "train_end": window.train_end, "test_start": context.test_start,
                "test_end": context.test_end,
                "parameter_identity_sha256": manifests[cid]["identity_sha256"],
                "score_rank_correlation_vs_baseline": diag["score_rank_correlation"],
                "final_top15_overlap_vs_baseline": diag["final_top15_overlap"],
                "cost_stress": cost_stress,
            })

    stability = summarize_walk_forward_reports(reports, min_windows=4)
    aggregates = [
        _aggregate_extended(cid, f"xgb:daily_ranker:{'+'.join(groups)}:native:{cid}",
                           manifests[cid], window_rows_by_candidate[cid])
        for cid, groups, _ in candidates_def
    ]
    decision = _decision_extended(
        aggregates, baseline_cid,
        provider_ok=(observed_provider == canonical_provider),
        deterministic_baseline=all(deterministic_checks),
    )
    payload = {
        "schema_version": "1.0", "experiment_id": EXTENDED_ID,
        "parent_model_id": "us_x1_1", "research_only": True, "trade_ready": False,
        "provider": {
            "canonical_identity_sha256": canonical_provider,
            "observed_identity_sha256": observed_provider,
            "matches_canonical": observed_provider == canonical_provider,
        },
        "decision_windows": list(DECISION_WINDOWS),
        "consumed_reporting_windows_excluded": ["2026H1"],
        "candidate_aggregates": aggregates,
        "walk_forward_stability": stability,
        "decision": decision,
    }
    _write_json(output_dir / "extended_grid_decision.json", payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("artifacts/evidence/us_x1_2_extended_grid_v1"))
    args = parser.parse_args()
    payload = run(args.root, provider_uri=args.provider_uri, output_dir=args.output_dir)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
