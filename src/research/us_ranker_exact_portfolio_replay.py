"""Canonical online replay for US ranker candidates under the US x1.2 portfolio contract.

Local agents may discover candidates against a separately recorded provider identity.
This verifier is the promotion-evidence boundary: GitHub Actions rebuilds the
canonical provider from repository sources, then this module refits the declared
rankers and evaluates the exact Top-15 / max-four-per-sector portfolio path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
from src.common.runtime_settings import PROJECT_ROOT
from src.research.cross_sectional_experiment_runner import (
    RETURN_EXPRESSION,
    _benchmark_instrument,
    _factor_expressions,
    _resolve_symbols,
    _runtime_for_market,
    load_cross_sectional_experiment_spec,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.experiment_harness import evaluate_experiment
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
from src.research.us87_sector_style import load_pool_symbols, load_sector_classification
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

REPLAY_ID = "exact_us_ranker_portfolio_v1"
TOP_N = 15
MAX_NAMES_PER_SECTOR = 4
BASE_COST_BPS = 20
STRESS_COST_BPS = 60


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_frame(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    if isinstance(canonical.index, pd.MultiIndex):
        canonical = canonical.sort_index()
    else:
        canonical = canonical.sort_index()
    payload = canonical.to_csv(index=True, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score_frame(scores: pd.DataFrame | pd.Series) -> pd.DataFrame:
    if isinstance(scores, pd.Series):
        frame = scores.rename("score").to_frame()
    else:
        frame = scores.copy()
        if "score" not in frame.columns:
            if len(frame.columns) != 1:
                raise ValueError("ranker score frame must contain exactly one score column")
            frame.columns = ["score"]
    frame = normalize_qlib_frame_index(frame)
    result = frame.reset_index()
    required = {"datetime", "instrument", "score"}
    if not required.issubset(result.columns):
        raise ValueError(f"ranker score frame is missing columns: {sorted(required - set(result))}")
    result["datetime"] = pd.to_datetime(result["datetime"])
    result["instrument"] = result["instrument"].astype(str)
    return result[["datetime", "instrument", "score"]].sort_values(
        ["datetime", "instrument"], kind="stable"
    ).reset_index(drop=True)


def _return_map(frame: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    normalized = normalize_qlib_frame_index(frame)
    if list(normalized.columns) != ["return"]:
        raise ValueError("return frame must expose one canonical 'return' column")
    rows = normalized.reset_index()
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for row in rows.itertuples(index=False):
        value = float(row.return)
        if not np.isfinite(value):
            continue
        result.setdefault(pd.Timestamp(row.datetime), {})[str(row.instrument)] = value
    return result


def _benchmark_map(frame: pd.DataFrame) -> dict[pd.Timestamp, float]:
    if list(frame.columns) != ["return"]:
        raise ValueError("benchmark frame must expose one canonical 'return' column")
    return {pd.Timestamp(index): float(value) for index, value in frame["return"].items()}


def _relative_excess(strategy_return: float, benchmark_return: float) -> float:
    return (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0


def _sector_contract(spec, symbols: list[str]) -> tuple[dict[str, str], str]:
    execution = dict(spec.raw.get("execution") or {})
    exact = dict(execution.get("exact_portfolio") or {})
    if str(exact.get("replay_id") or "") != REPLAY_ID:
        raise ValueError(f"execution.exact_portfolio.replay_id must be {REPLAY_ID!r}")
    if int(exact.get("top_n", 0)) != TOP_N:
        raise ValueError("exact US portfolio replay requires Top-15")
    if int(exact.get("maximum_names_per_sector", 0)) != MAX_NAMES_PER_SECTOR:
        raise ValueError("exact US portfolio replay requires max four names per sector")
    if str(exact.get("weighting") or "") != "equal_weight":
        raise ValueError("exact US portfolio replay requires equal weighting")
    classification_raw = str(exact.get("sector_classification") or "")
    if not classification_raw:
        raise ValueError("exact US portfolio replay requires sector classification")
    classification_path = (PROJECT_ROOT / classification_raw).resolve()
    classification_path.relative_to(PROJECT_ROOT.resolve())
    pool_path = (PROJECT_ROOT / str(spec.parent.universe["source"])).resolve()
    pool_symbols = load_pool_symbols(pool_path)
    if sorted(pool_symbols) != sorted(symbols):
        raise ValueError("exact US portfolio symbols differ from governed pool")
    classification, manifest = load_sector_classification(classification_path, pool_symbols)
    sectors = dict(zip(classification["symbol"], classification["sector"], strict=True))
    if set(sectors) != set(symbols):
        raise ValueError("sector classification does not cover the exact US universe")
    identity = str(manifest.get("records_sha256_verified") or "")
    if not identity:
        raise ValueError("sector classification identity is unavailable")
    return sectors, identity


def _window_plan(spec, runtime):
    parent = spec.parent
    walk_forward = parent.walk_forward
    strategy = parent.strategy
    calendar = runtime.calendar(
        str(walk_forward["requested_train_start"]),
        min(str(walk_forward["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("provider calendar is empty for exact replay range")
    available_end = min(
        pd.Timestamp(spec.contract.cutoff),
        pd.Timestamp(calendar.max()),
        pd.Timestamp(str(walk_forward["test_end"])),
    ).strftime("%Y-%m-%d")
    plan = build_window_sampling_plan(
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
    evaluation_dates = horizon_eligible_dates_by_window(plan, calendar)
    required = set(spec.contract.selection_windows)
    windows = [window for window in plan.selected_windows if window.label in required]
    missing = sorted(required - {window.label for window in windows})
    if missing:
        raise ValueError(f"exact replay selection windows unavailable: {missing}")
    return windows, evaluation_dates


def _candidate_scores(
    *,
    spec,
    candidate,
    expressions: tuple[str, ...],
    expression_columns: dict[str, str],
    features_train_all: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test_all: pd.DataFrame,
    window_label: str,
) -> pd.DataFrame:
    columns = [expression_columns[expression] for expression in expressions]
    features_train = features_train_all.loc[:, columns]
    valid, reason = validate_no_nan_inputs(
        features_train,
        context=f"US exact replay train/{window_label}/{candidate.candidate_id}",
    )
    if not valid:
        raise ValueError(reason)
    x_rank, y_rank, groups = prepare_ranker_frame(features_train, returns_train)
    fitted = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=candidate.calibration,
    )
    return predict_xgb_native_daily_ranker(
        fitted,
        features_test_all.loc[:, columns],
    )


def _support_boundary(receipt: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = {str(row["candidate_id"]): row for row in receipt["candidates"]}
    baseline_id = str(receipt["baseline_candidate_id"])
    leader_id = str(receipt["leader"])
    baseline = candidates[baseline_id]
    leader = candidates[leader_id]

    leader_rows = [
        row
        for row in observations
        if row["candidate_id"] == leader_id and row["cost_bps"] == BASE_COST_BPS
    ]
    positive_windows = sum(float(row["relative_excess"]) > 0.0 for row in leader_rows)
    mean_rank_ic = float(leader["mean_rank_ic"])
    improvement_20 = float(leader["compounded_relative_excess"]) - float(
        baseline["compounded_relative_excess"]
    )
    improvement_60 = float(leader["stress_compounded_relative_excess"]) - float(
        baseline["stress_compounded_relative_excess"]
    )
    drawdown_delta = float(leader["worst_drawdown"]) - float(baseline["worst_drawdown"])
    checks = {
        "beats_incumbent_20bps": improvement_20 > 0.0,
        "beats_incumbent_60bps": improvement_60 > 0.0,
        "at_least_three_of_four_positive_windows": positive_windows >= 3,
        "positive_mean_rank_ic": mean_rank_ic > 0.0,
        "sector_cap_enforced": float(leader.get("concentration", 1.0))
        <= MAX_NAMES_PER_SECTOR / TOP_N + 1e-12,
    }
    return {
        "leader": leader_id,
        "baseline": baseline_id,
        "improvement_vs_incumbent_20bps": improvement_20,
        "improvement_vs_incumbent_60bps": improvement_60,
        "worst_drawdown_delta_vs_incumbent": drawdown_delta,
        "positive_window_count": positive_windows,
        "mean_rank_ic": mean_rank_ic,
        "checks": checks,
        "supported_before_determinism": all(checks.values()),
    }


def run_exact_us_ranker_portfolio_replay(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "us":
        raise ValueError("exact US ranker portfolio replay supports US only")
    if str(spec.raw.get("online_validation") or "") != REPLAY_ID:
        raise ValueError(f"online_validation must be {REPLAY_ID!r}")
    if spec.contract.base_cost_bps != BASE_COST_BPS or spec.contract.stress_cost_bps != STRESS_COST_BPS:
        raise ValueError("exact US replay requires 20bps base and 60bps stress")
    if int(spec.parent.strategy["top_n"]) != TOP_N:
        raise ValueError("parent ranker contract must use Top-15")
    if int(spec.parent.strategy["holding_days"]) != 10 or int(spec.parent.strategy["rebalance_days"]) != 10:
        raise ValueError("exact US replay requires 10-session holding/rebalance")

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "stage_b"
    )
    output.mkdir(parents=True, exist_ok=True)

    runtime = _runtime_for_market(spec.market)
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    expected_provider = spec.contract.provider_identity_sha256
    if observed_provider != expected_provider:
        receipt = {
            "schema_version": "1.0",
            "experiment_id": spec.experiment_id,
            "runner": REPLAY_ID,
            "status": "data_blocked",
            "decision": "provider_identity_mismatch",
            "expected_provider_identity_sha256": expected_provider,
            "observed_provider_identity_sha256": observed_provider,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(output / "stage_b_receipt.json", receipt)
        return receipt

    symbols = _resolve_symbols(spec, runtime)
    sectors, sector_identity = _sector_contract(spec, symbols)
    benchmark_instrument = _benchmark_instrument(spec, runtime)
    windows, evaluation_dates_by_window = _window_plan(spec, runtime)
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
    candidate_metadata: dict[str, dict[str, Any]] = {
        candidate.candidate_id: {
            "role": candidate.role,
            "factor_groups": list(candidate.factor_groups),
            "factor_count": len(expressions_by_candidate[candidate.candidate_id]),
            "parameter_identity": candidate.calibration.identity_manifest(),
            "dominates_factor_baselines": False,
            "concentration": 0.0,
        }
        for candidate in spec.candidates
    }
    score_hashes: dict[str, dict[str, str]] = {candidate.candidate_id: {} for candidate in spec.candidates}
    replay_cache: dict[str, dict[str, Any]] = {}

    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, union_expressions, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
        test_mask = dates.isin(evaluation_dates)
        features_train_all, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        features_test_all = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument=benchmark_instrument,
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=evaluation_dates,
            start=window.test_start,
            end=window.test_end,
            provenance="raw_forward_return",
            horizon=10,
        )
        return_map = _return_map(returns_test)
        benchmark_map = _benchmark_map(benchmark)
        replay_cache[window.label] = {
            "features_train_all": features_train_all,
            "returns_train": returns_train,
            "features_test_all": features_test_all,
            "return_map": return_map,
            "benchmark_map": benchmark_map,
        }

        for candidate in spec.candidates:
            scores = _candidate_scores(
                spec=spec,
                candidate=candidate,
                expressions=expressions_by_candidate[candidate.candidate_id],
                expression_columns=expression_columns,
                features_train_all=features_train_all,
                returns_train=returns_train,
                features_test_all=features_test_all,
                window_label=window.label,
            )
            score_hashes[candidate.candidate_id][window.label] = _sha256_frame(
                normalize_qlib_frame_index(scores if isinstance(scores, pd.DataFrame) else scores.to_frame("score"))
            )
            score_frame = _score_frame(scores)
            rank_diagnostic = evaluate_candidate(
                scores,
                returns_test,
                candidate_kind=CandidateKind.XGB_RANK_NDCG,
                orientation=ScoreOrientation.ORIGINAL,
                benchmark_returns=benchmark,
                topk=TOP_N,
                rebalance_days=10,
                cost_bps=BASE_COST_BPS,
            ).to_dict()
            for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
                result, periods, _, selections, _ = sector_cap._evaluate(
                    score_frame,
                    return_map,
                    benchmark_map,
                    sectors,
                    cost_bps=cost_bps,
                    sector_cap=True,
                )
                selected = selections.loc[selections["challenger_selected"]]
                max_sector_weight = (
                    selected.groupby(["period_index", "sector"]).size().max() / TOP_N
                )
                candidate_metadata[candidate.candidate_id]["concentration"] = max(
                    float(candidate_metadata[candidate.candidate_id]["concentration"]),
                    float(max_sector_weight),
                )
                observations.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "window": window.label,
                        "cost_bps": cost_bps,
                        "relative_excess": _relative_excess(
                            float(result["total_return"]), float(result["benchmark_return"])
                        ),
                        "strategy_return": float(result["total_return"]),
                        "benchmark_return": float(result["benchmark_return"]),
                        "max_drawdown": float(result["max_drawdown"]),
                        "rank_ic": float(rank_diagnostic["rank_ic"]),
                        "icir": float(rank_diagnostic["icir"]),
                        "turnover": float(result["turnover"]),
                        "costs": float(result["costs"]),
                        "max_sector_weight": float(periods["max_sector_weight"].max()),
                    }
                )

    receipt = evaluate_experiment(
        spec.contract,
        observations,
        candidate_metadata=candidate_metadata,
    )
    receipt["baseline_candidate_id"] = spec.contract.baseline_candidate_id
    support = _support_boundary(receipt, observations)
    leader_id = str(support["leader"])
    leader = next(candidate for candidate in spec.candidates if candidate.candidate_id == leader_id)

    deterministic = True
    reproduction_hashes: dict[str, dict[str, str]] = {}
    for window in windows:
        cache = replay_cache[window.label]
        scores = _candidate_scores(
            spec=spec,
            candidate=leader,
            expressions=expressions_by_candidate[leader_id],
            expression_columns=expression_columns,
            features_train_all=cache["features_train_all"],
            returns_train=cache["returns_train"],
            features_test_all=cache["features_test_all"],
            window_label=window.label,
        )
        replay_hash = _sha256_frame(
            normalize_qlib_frame_index(scores if isinstance(scores, pd.DataFrame) else scores.to_frame("score"))
        )
        original_hash = score_hashes[leader_id][window.label]
        reproduction_hashes[window.label] = {
            "first": original_hash,
            "second": replay_hash,
        }
        deterministic = deterministic and replay_hash == original_hash

    support["exact_score_reproduction"] = deterministic
    support["supported"] = bool(support["supported_before_determinism"] and deterministic)
    receipt.update(
        {
            "status": "completed",
            "runner": REPLAY_ID,
            "observed_provider_identity_sha256": observed_provider,
            "sector_classification_identity_sha256": sector_identity,
            "candidate_metadata": candidate_metadata,
            "support_boundary": support,
            "score_reproduction": reproduction_hashes,
            "research_only": True,
            "trade_ready": False,
            "automatic_promotion": False,
            "stage_b_supported": bool(support["supported"]),
        }
    )
    _write_json(output / "observations.json", observations)
    _write_json(output / "stage_b_receipt.json", receipt)
    return receipt
