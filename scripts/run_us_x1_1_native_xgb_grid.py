"""Run the pre-registered US x1.1 native XGBoost calibration grid.

The experiment selects candidates only on complete 2024H1--2025H2 windows.
2026H1 remains consumed reporting evidence and is not loaded by this runner.
A provider identity mismatch does not suppress evidence generation, but it
forces the final version decision to ``data_blocked``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.daily_ranker import prepare_ranker_frame
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import (
    CandidateKind,
    ScoreOrientation,
    evaluate_candidate,
)
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

EXPERIMENT_CONFIG = Path(
    "configs/research_experiments/us_x1_1_native_xgb_calibration_v1.yaml"
)
MODEL_CONFIG = Path("configs/models/us_x1_1.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/us_selected_equities_v2.yaml")
EXPERIMENT_ID = "us_x1_1_native_xgb_grid_v1"
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
DECISION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
COST_STRESS_BPS = (20, 40, 60)
BASELINE_ID = "x1_1_effective_baseline"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def _relative(strategy_return: float, benchmark_return: float) -> float:
    return (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0


def _candidate_name(calibration_id: str, calibration: XGBNativeCalibration) -> str:
    return (
        "xgb:daily_ranker:momentum_volatility_volume:"
        f"native:{calibration_id}:{calibration.name}"
    )


def _native_calibrations(config: dict[str, Any]) -> list[tuple[str, XGBNativeCalibration]]:
    rows = config.get("native_calibrations", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("native_calibrations must be a non-empty list")
    result: list[tuple[str, XGBNativeCalibration]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("every native calibration must be a mapping")
        calibration_id = str(raw.get("calibration_id", "")).strip()
        if not calibration_id or calibration_id in seen_ids:
            raise ValueError(f"invalid or duplicate calibration_id: {calibration_id!r}")
        native = dict(raw)
        native.pop("calibration_id", None)
        calibration = XGBNativeCalibration.from_dict(native)
        identity = str(calibration.identity_manifest()["identity_sha256"])
        if identity in seen_hashes:
            raise ValueError("native calibrations must have unique effective identities")
        seen_ids.add(calibration_id)
        seen_hashes.add(identity)
        result.append((calibration_id, calibration))
    if BASELINE_ID not in seen_ids:
        raise ValueError(f"native grid must contain {BASELINE_ID!r}")
    return result


def _resolve_symbols(runtime: QlibUSExecutionRuntime, universe: dict[str, Any]) -> list[str]:
    requested = [str(item) for item in universe.get("symbols", [])]
    expected = int(universe.get("candidate_count", 0))
    if len(requested) != expected or len(requested) != len(set(requested)):
        raise ValueError("US selected-pool symbol contract is inconsistent")
    available = runtime.available_symbols()
    normalized = normalize_market_symbols(
        "us",
        requested,
        available_symbols=available,
    )
    resolved = [item.normalized_symbol for item in normalized]
    if len(resolved) != expected or len(resolved) != len(set(resolved)):
        raise ValueError(
            f"resolved {len(resolved)} unique symbols; expected {expected}"
        )
    missing = sorted(set(resolved) - available)
    if missing:
        raise ValueError(f"provider is missing selected-pool symbols: {missing}")
    return resolved


def _final_top(scores: pd.DataFrame, top_n: int = 15) -> list[str]:
    dates = scores.index.get_level_values("datetime")
    final_date = dates.max()
    final = scores.xs(final_date, level="datetime")["score"]
    return [str(item) for item in final.nlargest(min(top_n, len(final))).index]


def _score_diagnostics(
    baseline: pd.DataFrame,
    challenger: pd.DataFrame,
) -> dict[str, float]:
    common = baseline.index.intersection(challenger.index)
    correlation = baseline.loc[common, "score"].corr(
        challenger.loc[common, "score"],
        method="spearman",
    )
    baseline_top = set(_final_top(baseline))
    challenger_top = set(_final_top(challenger))
    overlap = len(baseline_top & challenger_top) / max(1, len(baseline_top))
    return {
        "score_rank_correlation": 0.0 if pd.isna(correlation) else float(correlation),
        "final_top15_overlap": float(overlap),
    }


def _original_result(report: dict[str, Any], candidate_name: str) -> dict[str, Any]:
    comparison = report.get("comparison_report", {})
    rows = comparison.get("candidates", []) if isinstance(comparison, dict) else []
    matches = [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and row.get("candidate_name") == candidate_name
        and row.get("candidate_kind") == "xgb_rank_ndcg"
        and row.get("orientation") == "original"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one original result for {candidate_name}")
    return matches[0]


def _stress_result(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    cost_bps: int,
) -> dict[str, Any]:
    result = evaluate_candidate(
        scores,
        returns,
        candidate_kind=CandidateKind.XGB_RANK_NDCG,
        orientation=ScoreOrientation.ORIGINAL,
        benchmark_returns=benchmark,
        topk=15,
        rebalance_days=10,
        cost_bps=cost_bps,
    )
    return result.to_dict()


def _aggregate_candidate(
    calibration_id: str,
    candidate_name: str,
    manifest: dict[str, Any],
    window_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(window_rows, key=lambda item: DECISION_WINDOWS.index(item["window"]))
    aggregates: dict[str, Any] = {}
    for cost in COST_STRESS_BPS:
        rows = [dict(item["cost_stress"][str(cost)]) for item in ordered]
        strategy = _compound([float(row["total_return"]) for row in rows])
        benchmark = _compound([float(row["benchmark_return"]) for row in rows])
        aggregates[str(cost)] = {
            "compounded_strategy_return": strategy,
            "compounded_benchmark_return": benchmark,
            "compounded_relative_excess_return": _relative(strategy, benchmark),
        }
    base_rows = [dict(item["cost_stress"]["20"]) for item in ordered]
    simple_excess = [float(row["excess_return"]) for row in base_rows]
    positive = [value for value in simple_excess if value > 0]
    recurring = set(str(item) for item in base_rows[0].get("top_selected_stocks", []))
    for row in base_rows[1:]:
        recurring &= set(str(item) for item in row.get("top_selected_stocks", []))
    strongest_share = max(positive) / sum(positive) if positive else 1.0
    return {
        "calibration_id": calibration_id,
        "candidate_name": candidate_name,
        "parameter_identity": manifest,
        "n_windows": len(ordered),
        "positive_excess_windows": sum(value > 0 for value in simple_excess),
        "mean_icir": float(np.mean([float(row["icir"]) for row in base_rows])),
        "mean_rank_ic": float(np.mean([float(row["rank_ic"]) for row in base_rows])),
        "mean_spread": float(
            np.mean(
                [
                    float(row["score_direction"]["top_minus_bottom_spread"])
                    for row in base_rows
                ]
            )
        ),
        "worst_drawdown": min(float(row["max_drawdown"]) for row in base_rows),
        "strongest_positive_window_share": float(strongest_share),
        "all_window_recurring_names": sorted(recurring),
        "mean_score_rank_correlation_vs_baseline": float(
            np.mean([float(item["score_rank_correlation_vs_baseline"]) for item in ordered])
        ),
        "mean_final_top15_overlap_vs_baseline": float(
            np.mean([float(item["final_top15_overlap_vs_baseline"]) for item in ordered])
        ),
        "cost_stress": aggregates,
        "windows": ordered,
    }


def _decision(
    aggregates: list[dict[str, Any]],
    *,
    provider_matches_baseline: bool,
    deterministic_baseline: bool,
) -> dict[str, Any]:
    by_id = {str(item["calibration_id"]): item for item in aggregates}
    baseline = by_id[BASELINE_ID]
    baseline_relative = float(
        baseline["cost_stress"]["20"]["compounded_relative_excess_return"]
    )
    baseline_dd = float(baseline["worst_drawdown"])
    baseline_rank_ic = float(baseline["mean_rank_ic"])
    evaluated: list[dict[str, Any]] = []
    for row in aggregates:
        if row["calibration_id"] == BASELINE_ID:
            continue
        relative20 = float(
            row["cost_stress"]["20"]["compounded_relative_excess_return"]
        )
        relative60 = float(
            row["cost_stress"]["60"]["compounded_relative_excess_return"]
        )
        gates = {
            "four_positive_excess_windows": int(row["positive_excess_windows"]) == 4,
            "positive_60_bps_relative_excess": relative60 > 0,
            "retain_at_least_90pct_baseline_relative_excess": (
                relative20 >= 0.90 * baseline_relative
            ),
            "drawdown_improves_3pp_or_stays_above_minus_22pct": (
                float(row["worst_drawdown"]) >= baseline_dd + 0.03
                or float(row["worst_drawdown"]) >= -0.22
            ),
            "mean_rank_ic_not_materially_weaker": (
                float(row["mean_rank_ic"]) >= max(0.0, baseline_rank_ic - 0.005)
            ),
            "strongest_window_share_below_55pct": (
                float(row["strongest_positive_window_share"]) < 0.55
            ),
        }
        penalty = max(0.0, -float(row["worst_drawdown"]) - 0.22)
        selection_score = (
            relative20
            - 1.5 * penalty
            + 0.15 * float(row["mean_icir"])
            + 0.10 * float(row["mean_rank_ic"])
            + 0.10 * (1.0 - float(row["strongest_positive_window_share"]))
        )
        evaluated.append(
            {
                "calibration_id": row["calibration_id"],
                "gates": gates,
                "all_gates_pass": all(gates.values()),
                "selection_score": selection_score,
            }
        )
    supported = sorted(
        [item for item in evaluated if item["all_gates_pass"]],
        key=lambda item: float(item["selection_score"]),
        reverse=True,
    )
    if not provider_matches_baseline:
        decision = "data_blocked"
        selected = None
    elif not deterministic_baseline:
        decision = "native_grid_unstable"
        selected = None
    elif supported:
        decision = "native_xgb_x1_2_candidate_supported"
        selected = supported[0]["calibration_id"]
    elif (
        int(baseline["positive_excess_windows"]) == 4
        and float(
            baseline["cost_stress"]["60"]["compounded_relative_excess_return"]
        )
        > 0
    ):
        decision = "us_x1_1_native_runtime_preferred"
        selected = BASELINE_ID
    else:
        decision = "native_grid_unstable"
        selected = None
    return {
        "decision": decision,
        "selected_calibration_id": selected,
        "provider_matches_baseline": provider_matches_baseline,
        "deterministic_baseline_rerun": deterministic_baseline,
        "candidate_gate_results": evaluated,
        "automatic_model_update": False,
        "may_create_reviewed_us_x1_2_candidate": (
            decision == "native_xgb_x1_2_candidate_supported"
        ),
        "new_untouched_challenge_required": True,
    }


def run(
    root: Path,
    *,
    provider_uri: Path,
    output_dir: Path = Path("artifacts/evidence/us_x1_1_native_xgb_grid_v1"),
) -> dict[str, Any]:
    root = root.resolve()
    provider_uri = provider_uri.resolve()
    output_dir = output_dir.resolve()
    experiment = _load_yaml(root / EXPERIMENT_CONFIG)
    model = _load_yaml(root / MODEL_CONFIG)
    universe = _load_yaml(root / UNIVERSE_CONFIG)
    calibrations = _native_calibrations(experiment)
    feature_expressions = [str(item) for item in model["features"]["expressions"]]
    canonical_provider = str(
        model["provider_binding"]["canonical_evidence_provider_identity_sha256"]
    )

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    runtime_meta = runtime.metadata()
    observed_provider = str(runtime_meta.get("provider_identity_sha256", ""))
    provider_manifest = _load_json(provider_uri / "provider_manifest.json")
    symbols = _resolve_symbols(runtime, universe)
    calendar = runtime.calendar("2021-01-01", "2025-12-31")
    available_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar,
        "2021-01-01",
        available_end,
        first_test_year=2024,
        last_test_year=2025,
        min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    windows = list(window_plan.selected_windows)
    if tuple(window.label for window in windows) != DECISION_WINDOWS:
        raise ValueError(
            f"unexpected decision windows: {[window.label for window in windows]}"
        )
    evaluation_dates_by_window = horizon_eligible_dates_by_window(window_plan, calendar)

    candidate_names = {
        calibration_id: _candidate_name(calibration_id, calibration)
        for calibration_id, calibration in calibrations
    }
    manifests = {
        calibration_id: calibration.identity_manifest()
        for calibration_id, calibration in calibrations
    }
    window_rows_by_candidate: dict[str, list[dict[str, Any]]] = {
        calibration_id: [] for calibration_id, _ in calibrations
    }
    reports: list[dict[str, Any]] = []
    deterministic_checks: list[bool] = []

    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                feature_expressions,
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{index}" for index in range(len(feature_expressions))]
        returns_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        )
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": RETURN_EXPRESSION,
            }
        )
        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (
            dates <= pd.Timestamp(window.train_end)
        )
        test_mask = dates.isin(evaluation_dates)
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        valid, reason = validate_no_nan_inputs(
            features_train,
            context=f"US x1.1 native grid train/{window.label}",
        )
        if not valid:
            raise ValueError(reason)
        features_test = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)
        x_rank, y_rank, groups = prepare_ranker_frame(features_train, returns_train)

        scores_by_id: dict[str, pd.DataFrame] = {}
        for calibration_id, calibration in calibrations:
            fitted = fit_xgb_native_daily_ranker(
                x_rank,
                y_rank,
                groups,
                calibration=calibration,
            )
            scores_by_id[calibration_id] = predict_xgb_native_daily_ranker(
                fitted,
                features_test,
            )
        baseline_scores = scores_by_id[BASELINE_ID]
        baseline_calibration = dict(calibrations)[BASELINE_ID]
        repeated = fit_xgb_native_daily_ranker(
            x_rank,
            y_rank,
            groups,
            calibration=baseline_calibration,
        )
        repeated_scores = predict_xgb_native_daily_ranker(repeated, features_test)
        deterministic_checks.append(
            bool(
                np.allclose(
                    baseline_scores["score"].to_numpy(),
                    repeated_scores["score"].to_numpy(),
                    rtol=0.0,
                    atol=1e-12,
                )
            )
        )

        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument="QQQ",
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=evaluation_dates,
            start=evaluation_dates.min().strftime("%Y-%m-%d"),
            end=evaluation_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return",
            horizon=10,
        )
        context = SpecBoundEvaluationContext(
            market="us",
            symbols=tuple(symbols),
            benchmark="QQQ",
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=evaluation_dates.min().strftime("%Y-%m-%d"),
            test_end=evaluation_dates.max().strftime("%Y-%m-%d"),
            holding_days=10,
            rebalance_days=10,
            topk=15,
            model_type="us_x1_1_native_xgb_grid",
            factor_expressions=tuple(feature_expressions),
            return_expression=RETURN_EXPRESSION,
            experiment_id=f"{EXPERIMENT_ID}_{window.label}",
        )
        named_scores = {
            candidate_names[calibration_id]: scores
            for calibration_id, scores in scores_by_id.items()
        }
        report = run_10d_experiment(
            config=context,
            candidates=named_scores,
            raw_returns=returns_test,
            benchmark_returns=benchmark,
            output_dir=output_dir / "windows",
        )
        report["provider_identity_sha256"] = observed_provider
        report["parameter_manifests"] = manifests
        report["deterministic_baseline_rerun"] = deterministic_checks[-1]
        report["score_diagnostics_vs_baseline"] = {
            calibration_id: _score_diagnostics(baseline_scores, scores)
            for calibration_id, scores in scores_by_id.items()
        }
        if report.get("artifact_path"):
            _write_json(
                Path(str(report["artifact_path"])),
                {key: value for key, value in report.items() if key != "artifact_path"},
            )
        reports.append(report)

        for calibration_id, scores in scores_by_id.items():
            candidate_name = candidate_names[calibration_id]
            cost_stress: dict[str, Any] = {
                "20": _original_result(report, candidate_name)
            }
            for cost in (40, 60):
                cost_stress[str(cost)] = _stress_result(
                    scores,
                    returns_test,
                    benchmark,
                    cost_bps=cost,
                )
            diagnostics = _score_diagnostics(baseline_scores, scores)
            window_rows_by_candidate[calibration_id].append(
                {
                    "window": window.label,
                    "train_start": window.train_start,
                    "train_end": window.train_end,
                    "test_start": context.test_start,
                    "test_end": context.test_end,
                    "parameter_identity_sha256": manifests[calibration_id][
                        "identity_sha256"
                    ],
                    "score_rank_correlation_vs_baseline": diagnostics[
                        "score_rank_correlation"
                    ],
                    "final_top15_overlap_vs_baseline": diagnostics[
                        "final_top15_overlap"
                    ],
                    "cost_stress": cost_stress,
                }
            )

    stability = summarize_walk_forward_reports(reports, min_windows=4)
    aggregates = [
        _aggregate_candidate(
            calibration_id,
            candidate_names[calibration_id],
            manifests[calibration_id],
            window_rows_by_candidate[calibration_id],
        )
        for calibration_id, _ in calibrations
    ]
    decision = _decision(
        aggregates,
        provider_matches_baseline=(observed_provider == canonical_provider),
        deterministic_baseline=all(deterministic_checks),
    )
    payload = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "parent_model_id": "us_x1_1",
        "issue": 370,
        "growth_ledger_issue": 374,
        "research_only": True,
        "trade_ready": False,
        "provider": {
            "canonical_identity_sha256": canonical_provider,
            "observed_identity_sha256": observed_provider,
            "matches_canonical": observed_provider == canonical_provider,
            "manifest": provider_manifest,
        },
        "decision_windows": list(DECISION_WINDOWS),
        "consumed_reporting_windows_excluded": ["2026H1"],
        "attempted_candidates": len(calibrations),
        "candidate_aggregates": aggregates,
        "walk_forward_stability": stability,
        "decision": decision,
    }
    _write_json(output_dir / "native_grid_decision.json", payload)
    _write_json(output_dir / "walk_forward_stability.json", stability)
    _write_json(
        output_dir / "parameter_identity_manifest.json",
        {
            "schema_version": "1.0",
            "experiment_id": EXPERIMENT_ID,
            "candidates": manifests,
        },
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_native_xgb_grid_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
