"""Reusable spec-driven cross-sectional XGBoost research runner.

The runner owns execution only. Window roles, ranking, and support gates remain
owned by :mod:`src.research.experiment_harness` so candidate code cannot change
selection semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.economics import relative_excess
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.experiment_harness import (
    ExperimentContract,
    evaluate_experiment,
    load_experiment_contract,
)
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.paradigm import ResearchParadigmSpec
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    benchmark_instrument as _benchmark_instrument,
    factor_expressions as _factor_expressions,
    resolve_symbols as _resolve_symbols,
    runtime_for_market as _runtime_for_market,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import (
    CandidateKind,
    ScoreOrientation,
    evaluate_candidate,
)
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import XGBNativeCalibration

RUNNER_ID = "cross_sectional_xgb_ranker_v1"


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    role: str
    factor_groups: tuple[str, ...]
    calibration: XGBNativeCalibration


@dataclass(frozen=True)
class CrossSectionalExperimentSpec:
    path: Path
    raw: dict[str, Any]
    contract: ExperimentContract
    parent: ResearchParadigmSpec
    factor_library_path: Path
    candidates: tuple[CandidateSpec, ...]

    @property
    def experiment_id(self) -> str:
        return self.contract.experiment_id

    @property
    def market(self) -> str:
        return self.parent.market

    @property
    def benchmark(self) -> str:
        return self.parent.benchmark


def _yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def _resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"research path escapes repository root: {raw}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def load_cross_sectional_experiment_spec(
    path: str | Path,
) -> CrossSectionalExperimentSpec:
    resolved = _resolve_repo_path(str(path))
    raw = _yaml_mapping(resolved)
    if str(raw.get("runner", "")) != RUNNER_ID:
        raise ValueError(f"experiment runner must be {RUNNER_ID!r}")
    if raw.get("research_only") is not True or raw.get("trade_ready") is not False:
        raise ValueError("research experiment must be research_only=true, trade_ready=false")

    contract = load_experiment_contract(resolved)
    fixed_model = raw.get("fixed_model") or {}
    parent_path = _resolve_repo_path(str(fixed_model.get("frozen_spec", "")))
    parent = ResearchParadigmSpec.from_yaml(parent_path)
    if parent.market not in {"us", "cn"}:
        raise ValueError("cross-sectional ranker runner supports only US/CN")
    if str(parent.strategy.get("return_expression")) != RETURN_EXPRESSION:
        raise ValueError("parent paradigm must use the canonical 10D return expression")

    factor_cfg = raw.get("factor_library") or {}
    factor_library_path = _resolve_repo_path(str(factor_cfg.get("source", "")))
    library = load_factor_library(factor_library_path)

    rows = raw.get("candidates")
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("candidates must contain baseline and at least one challenger")
    candidates: list[CandidateSpec] = []
    seen: set[str] = set()
    baseline_count = 0
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("candidate entries must be mappings")
        candidate_id = str(item.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in seen:
            raise ValueError(f"invalid or duplicate candidate_id: {candidate_id!r}")
        seen.add(candidate_id)
        role = str(item.get("role", "challenger"))
        if role not in {"baseline", "challenger"}:
            raise ValueError(f"unsupported candidate role: {role}")
        if role == "baseline":
            baseline_count += 1
        factor_groups = tuple(str(value) for value in item.get("factor_groups", []))
        if not factor_groups or len(set(factor_groups)) != len(factor_groups):
            raise ValueError(f"candidate {candidate_id} has invalid factor_groups")
        select_factor_groups(library, list(factor_groups))
        calibration_raw = item.get("xgb_native")
        if not isinstance(calibration_raw, dict):
            raise ValueError(f"candidate {candidate_id} requires xgb_native mapping")
        candidates.append(
            CandidateSpec(
                candidate_id=candidate_id,
                role=role,
                factor_groups=factor_groups,
                calibration=XGBNativeCalibration.from_dict(dict(calibration_raw)),
            )
        )
    if baseline_count != 1:
        raise ValueError("experiment must declare exactly one baseline candidate")
    baseline = next(item for item in candidates if item.role == "baseline")
    if baseline.candidate_id != contract.baseline_candidate_id:
        raise ValueError("evaluation baseline_candidate_id must match baseline candidate")

    return CrossSectionalExperimentSpec(
        path=resolved,
        raw=raw,
        contract=contract,
        parent=parent,
        factor_library_path=factor_library_path,
        candidates=tuple(candidates),
    )


def _original_result(report: dict[str, Any], candidate_name: str) -> dict[str, Any]:
    comparison = report.get("comparison_report") or {}
    rows = comparison.get("candidates", []) if isinstance(comparison, dict) else []
    matches = [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and row.get("candidate_name") == candidate_name
        and row.get("candidate_kind") == CandidateKind.XGB_RANK_NDCG.value
        and row.get("orientation") == ScoreOrientation.ORIGINAL.value
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one original result for {candidate_name}")
    return matches[0]


def _result_to_observation(
    *,
    candidate_id: str,
    window: str,
    cost_bps: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    strategy_return = float(result["total_return"])
    benchmark_return = float(result["benchmark_return"])
    return {
        "candidate_id": candidate_id,
        "window": window,
        "cost_bps": cost_bps,
        "relative_excess": relative_excess(strategy_return, benchmark_return),
        "strategy_return": strategy_return,
        "benchmark_return": benchmark_return,
        "max_drawdown": float(result["max_drawdown"]),
        "rank_ic": float(result["rank_ic"]),
        "icir": float(result["icir"]),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_cross_sectional_experiment(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)

    runtime = _runtime_for_market(spec.market)
    runtime.initialize(PROJECT_ROOT)
    runtime_metadata = runtime.metadata()
    observed_provider = str(runtime_metadata.get("provider_identity_sha256", ""))
    expected_provider = spec.contract.provider_identity_sha256
    if observed_provider != expected_provider:
        receipt = {
            "schema_version": "1.0",
            "experiment_id": spec.experiment_id,
            "status": "data_blocked",
            "expected_provider_identity_sha256": expected_provider,
            "observed_provider_identity_sha256": observed_provider,
            "supported": False,
            "decision": "data_blocked",
        }
        _write_json(output / "research_receipt.json", receipt)
        return receipt

    symbols = _resolve_symbols(spec, runtime)
    benchmark_instrument = _benchmark_instrument(spec, runtime)
    parent = spec.parent
    walk_forward = parent.walk_forward
    strategy = parent.strategy
    calendar = runtime.calendar(
        str(walk_forward["requested_train_start"]),
        min(str(walk_forward["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("provider calendar is empty for experiment range")
    available_end = min(
        pd.Timestamp(spec.contract.cutoff),
        pd.Timestamp(calendar.max()),
        pd.Timestamp(str(walk_forward["test_end"])),
    ).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar,
        str(walk_forward["requested_train_start"]),
        available_end,
        first_test_year=int(walk_forward["first_test_year"]),
        last_test_year=int(walk_forward["last_test_year"]),
        min_complete_windows=int(walk_forward["min_windows"]),
        partial_window_policy=str(walk_forward["partial_window_policy"]),
        min_partial_window_eligible_sessions=int(
            walk_forward["min_partial_window_eligible_sessions"]
        ),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    evaluation_dates_by_window = horizon_eligible_dates_by_window(window_plan, calendar)
    required_windows = set(spec.contract.selection_windows) | set(spec.contract.reporting_windows)
    windows = [
        window for window in window_plan.selected_windows if window.label in required_windows
    ]
    missing_windows = sorted(required_windows - {window.label for window in windows})
    if missing_windows:
        raise ValueError(f"mission windows unavailable: {missing_windows}")

    expressions_by_candidate = _factor_expressions(spec)
    union_expressions: list[str] = []
    for expressions in expressions_by_candidate.values():
        for expression in expressions:
            if expression not in union_expressions:
                union_expressions.append(expression)
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(union_expressions)
    }

    observations: list[dict[str, Any]] = []
    candidate_metadata: dict[str, dict[str, Any]] = {}
    window_reports: list[str] = []
    cost_levels = sorted({int(value) for value in spec.raw["execution"]["cost_stress_bps"]})
    for candidate in spec.candidates:
        candidate_metadata[candidate.candidate_id] = {
            "role": candidate.role,
            "factor_groups": list(candidate.factor_groups),
            "factor_count": len(expressions_by_candidate[candidate.candidate_id]),
            "parameter_identity": candidate.calibration.identity_manifest(),
            "dominates_factor_baselines": False,
            "concentration": 1.0,
        }

    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                union_expressions,
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": int(strategy["horizon_days"]),
                "expression": RETURN_EXPRESSION,
            }
        )
        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (
            dates <= pd.Timestamp(window.train_end)
        )
        test_mask = dates.isin(evaluation_dates)
        features_train_all, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=int(strategy["holding_days"]),
        )
        features_test_all = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument=benchmark_instrument,
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=evaluation_dates,
            start=window.test_start,
            end=window.test_end,
            provenance="raw_forward_return",
            horizon=int(strategy["horizon_days"]),
        )

        named_scores: dict[str, pd.DataFrame] = {}
        names_by_id: dict[str, str] = {}
        scores_by_id: dict[str, pd.DataFrame] = {}
        for candidate in spec.candidates:
            scores = fit_predict_ranker_scores(
                expressions=expressions_by_candidate[candidate.candidate_id],
                expression_columns=expression_columns,
                features_train=features_train_all,
                returns_train=returns_train,
                features_test=features_test_all,
                calibration=candidate.calibration,
                context=(
                    f"{spec.market.upper()} {spec.experiment_id} "
                    f"train/{window.label}/{candidate.candidate_id}"
                ),
            )
            candidate_name = (
                f"xgb:daily_ranker:{candidate.candidate_id}:native:{candidate.calibration.name}"
            )
            names_by_id[candidate.candidate_id] = candidate_name
            scores_by_id[candidate.candidate_id] = scores
            named_scores[candidate_name] = scores

        context = SpecBoundEvaluationContext(
            market=spec.market,
            symbols=tuple(symbols),
            benchmark=spec.benchmark,
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            holding_days=int(strategy["holding_days"]),
            rebalance_days=int(strategy["rebalance_days"]),
            topk=int(strategy["top_n"]),
            model_type="native_xgb_cross_sectional_ranker",
            factor_expressions=tuple(union_expressions),
            return_expression=RETURN_EXPRESSION,
            experiment_id=f"{spec.experiment_id}_{window.label}",
        )
        report = run_10d_experiment(
            config=context,
            candidates=named_scores,
            raw_returns=returns_test,
            benchmark_returns=benchmark,
            output_dir=output / "windows",
        )
        report["provider_identity_sha256"] = observed_provider
        report["candidate_parameter_identities"] = {
            candidate.candidate_id: candidate.calibration.identity_manifest()
            for candidate in spec.candidates
        }
        if report.get("artifact_path"):
            artifact = Path(str(report["artifact_path"]))
            _write_json(
                artifact,
                {key: value for key, value in report.items() if key != "artifact_path"},
            )
            window_reports.append(str(artifact))

        for candidate in spec.candidates:
            candidate_name = names_by_id[candidate.candidate_id]
            base_result = _original_result(report, candidate_name)
            by_cost: dict[int, dict[str, Any]] = {int(spec.contract.base_cost_bps): base_result}
            for cost_bps in cost_levels:
                if cost_bps == spec.contract.base_cost_bps:
                    continue
                by_cost[cost_bps] = evaluate_candidate(
                    scores_by_id[candidate.candidate_id],
                    returns_test,
                    candidate_kind=CandidateKind.XGB_RANK_NDCG,
                    orientation=ScoreOrientation.ORIGINAL,
                    benchmark_returns=benchmark,
                    topk=int(strategy["top_n"]),
                    rebalance_days=int(strategy["rebalance_days"]),
                    cost_bps=cost_bps,
                ).to_dict()
            for cost_bps, result in sorted(by_cost.items()):
                observations.append(
                    _result_to_observation(
                        candidate_id=candidate.candidate_id,
                        window=window.label,
                        cost_bps=cost_bps,
                        result=result,
                    )
                )

    receipt = evaluate_experiment(
        spec.contract,
        observations,
        candidate_metadata=candidate_metadata,
    )
    receipt.update(
        {
            "status": "completed",
            "runner": RUNNER_ID,
            "market": spec.market,
            "benchmark": spec.benchmark,
            "observed_provider_identity_sha256": observed_provider,
            "candidate_metadata": candidate_metadata,
            "window_report_paths": window_reports,
            "research_only": True,
            "trade_ready": False,
            "automatic_promotion": False,
        }
    )
    _write_json(output / "observations.json", observations)
    _write_json(output / "research_receipt.json", receipt)
    return receipt
