"""Exact US ranker Stage-B replay under the governed US portfolio contract."""

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
from src.research.economics import relative_excess
from src.research.experiment_harness import evaluate_experiment
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us87_sector_style import load_pool_symbols, load_sector_classification
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window
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


def _score_hash(scores: pd.DataFrame | pd.Series) -> str:
    frame = scores.rename("score").to_frame() if isinstance(scores, pd.Series) else scores.copy()
    frame = normalize_qlib_frame_index(frame).sort_index()
    payload = frame.to_csv(index=True, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score_frame(scores: pd.DataFrame | pd.Series) -> pd.DataFrame:
    frame = scores.rename("score").to_frame() if isinstance(scores, pd.Series) else scores.copy()
    if "score" not in frame.columns:
        if len(frame.columns) != 1:
            raise ValueError("ranker score frame must contain one score column")
        frame.columns = ["score"]
    result = normalize_qlib_frame_index(frame).reset_index()
    required = {"datetime", "instrument", "score"}
    if not required.issubset(result.columns):
        raise ValueError(f"ranker score frame missing {sorted(required - set(result))}")
    result["datetime"] = pd.to_datetime(result["datetime"])
    result["instrument"] = result["instrument"].astype(str)
    return result[["datetime", "instrument", "score"]].sort_values(
        ["datetime", "instrument"], kind="stable"
    ).reset_index(drop=True)


def _return_map(frame: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    normalized = normalize_qlib_frame_index(frame)
    if list(normalized.columns) != ["return"]:
        raise ValueError("return frame must expose one canonical 'return' column")
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for index, raw_value in normalized["return"].items():
        if not isinstance(index, tuple) or len(index) != 2:
            raise ValueError("return frame must use (datetime, instrument) index")
        date, instrument = index
        value = float(raw_value)
        if np.isfinite(value):
            result.setdefault(pd.Timestamp(date), {})[str(instrument)] = value
    return result


def _benchmark_map(frame: pd.DataFrame) -> dict[pd.Timestamp, float]:
    if list(frame.columns) != ["return"]:
        raise ValueError("benchmark frame must expose one canonical 'return' column")
    return {pd.Timestamp(index): float(value) for index, value in frame["return"].items()}


def _sectors(spec, symbols: list[str]) -> tuple[dict[str, str], str]:
    exact = dict((spec.raw.get("execution") or {}).get("exact_portfolio") or {})
    expected = {
        "replay_id": REPLAY_ID,
        "top_n": TOP_N,
        "weighting": "equal_weight",
        "maximum_names_per_sector": MAX_NAMES_PER_SECTOR,
        "holding_sessions": 10,
        "rebalance_sessions": 10,
    }
    for key, value in expected.items():
        if exact.get(key) != value:
            raise ValueError(f"exact portfolio contract drifted at {key}: {exact.get(key)!r}")
    classification = str(exact.get("sector_classification") or "")
    if not classification:
        raise ValueError("exact portfolio requires sector_classification")
    classification_path = (PROJECT_ROOT / classification).resolve()
    classification_path.relative_to(PROJECT_ROOT.resolve())
    pool_path = (PROJECT_ROOT / str(spec.parent.universe["source"])).resolve()
    pool_symbols = load_pool_symbols(pool_path)
    if sorted(pool_symbols) != sorted(symbols):
        raise ValueError("runtime symbols differ from governed US pool")
    frame, manifest = load_sector_classification(classification_path, pool_symbols)
    mapping = dict(zip(frame["symbol"], frame["sector"], strict=True))
    if set(mapping) != set(symbols):
        raise ValueError("sector classification does not cover runtime symbols")
    identity = str(manifest.get("records_sha256_verified") or "")
    if not identity:
        raise ValueError("sector classification identity is unavailable")
    return mapping, identity


def _windows(spec, runtime):
    walk = spec.parent.walk_forward
    strategy = spec.parent.strategy
    calendar = runtime.calendar(
        str(walk["requested_train_start"]),
        min(str(walk["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("provider calendar is empty")
    available_end = min(
        pd.Timestamp(spec.contract.cutoff),
        pd.Timestamp(calendar.max()),
        pd.Timestamp(str(walk["test_end"])),
    ).strftime("%Y-%m-%d")
    plan = build_window_sampling_plan(
        calendar,
        str(walk["requested_train_start"]),
        available_end,
        first_test_year=int(walk["first_test_year"]),
        last_test_year=int(walk["last_test_year"]),
        min_complete_windows=int(walk["min_windows"]),
        partial_window_policy=str(walk["partial_window_policy"]),
        min_partial_window_eligible_sessions=int(walk["min_partial_window_eligible_sessions"]),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    dates = horizon_eligible_dates_by_window(plan, calendar)
    required = set(spec.contract.selection_windows)
    selected = [window for window in plan.selected_windows if window.label in required]
    missing = sorted(required - {window.label for window in selected})
    if missing:
        raise ValueError(f"selection windows unavailable: {missing}")
    return selected, dates


def _fit_scores(
    candidate,
    expressions: tuple[str, ...],
    expression_columns: dict[str, str],
    features_train_all: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test_all: pd.DataFrame,
    window: str,
) -> pd.DataFrame:
    columns = [expression_columns[item] for item in expressions]
    train = features_train_all.loc[:, columns]
    valid, reason = validate_no_nan_inputs(
        train,
        context=f"US exact replay train/{window}/{candidate.candidate_id}",
    )
    if not valid:
        raise ValueError(reason)
    x_rank, y_rank, groups = prepare_ranker_frame(train, returns_train)
    fitted = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=candidate.calibration,
    )
    return predict_xgb_native_daily_ranker(fitted, features_test_all.loc[:, columns])


def _support_boundary(
    receipt: dict[str, Any], observations: list[dict[str, Any]], baseline_id: str
) -> dict[str, Any]:
    rows = {str(row["candidate_id"]): row for row in receipt["candidates"]}
    leader_id = str(receipt["leader"])
    baseline = rows[baseline_id]
    leader = rows[leader_id]
    leader_base = [
        row
        for row in observations
        if row["candidate_id"] == leader_id and row["cost_bps"] == BASE_COST_BPS
    ]
    improvement_20 = float(leader["compounded_relative_excess"]) - float(
        baseline["compounded_relative_excess"]
    )
    improvement_60 = float(leader["stress_compounded_relative_excess"]) - float(
        baseline["stress_compounded_relative_excess"]
    )
    positive_windows = sum(float(row["relative_excess"]) > 0.0 for row in leader_base)
    checks = {
        "beats_incumbent_20bps": improvement_20 > 0.0,
        "beats_incumbent_60bps": improvement_60 > 0.0,
        "at_least_three_of_four_positive_windows": positive_windows >= 3,
        "positive_mean_rank_ic": float(leader["mean_rank_ic"]) > 0.0,
        "sector_cap_enforced": float(leader.get("concentration", 1.0))
        <= MAX_NAMES_PER_SECTOR / TOP_N + 1e-12,
    }
    return {
        "leader": leader_id,
        "baseline": baseline_id,
        "improvement_vs_incumbent_20bps": improvement_20,
        "improvement_vs_incumbent_60bps": improvement_60,
        "worst_drawdown_delta_vs_incumbent": float(leader["worst_drawdown"])
        - float(baseline["worst_drawdown"]),
        "positive_window_count": positive_windows,
        "mean_rank_ic": float(leader["mean_rank_ic"]),
        "checks": checks,
        "supported_before_determinism": all(checks.values()),
    }


def run_exact_us_ranker_portfolio_replay(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "us" or str(spec.raw.get("online_validation") or "") != REPLAY_ID:
        raise ValueError("spec is not opted into exact US online replay")
    if spec.contract.base_cost_bps != BASE_COST_BPS or spec.contract.stress_cost_bps != STRESS_COST_BPS:
        raise ValueError("exact replay requires 20/60 bps")
    strategy = spec.parent.strategy
    if int(strategy["top_n"]) != TOP_N or int(strategy["holding_days"]) != 10 or int(strategy["rebalance_days"]) != 10:
        raise ValueError("parent strategy does not match the governed US 10D Top-15 contract")

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "stage_b"
    )
    output.mkdir(parents=True, exist_ok=True)

    runtime = _runtime_for_market("us")
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    expected_provider = spec.contract.provider_identity_sha256
    if observed_provider != expected_provider:
        blocked = {
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
        _write_json(output / "stage_b_receipt.json", blocked)
        return blocked

    symbols = _resolve_symbols(spec, runtime)
    sectors, sector_identity = _sectors(spec, symbols)
    benchmark_symbol = _benchmark_instrument(spec, runtime)
    windows, evaluation_dates = _windows(spec, runtime)
    expressions_by_candidate = _factor_expressions(spec)
    union_expressions = list(
        dict.fromkeys(
            expression
            for expressions in expressions_by_candidate.values()
            for expression in expressions
        )
    )
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(union_expressions)
    }

    observations: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {
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
    score_hashes: dict[str, dict[str, str]] = {
        candidate.candidate_id: {} for candidate in spec.candidates
    }
    cache: dict[str, dict[str, Any]] = {}

    for window in windows:
        dates = evaluation_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, union_expressions, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": RETURN_EXPRESSION,
            }
        )
        all_dates = features_all.index.get_level_values("datetime")
        train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
            all_dates <= pd.Timestamp(window.train_end)
        )
        test_mask = all_dates.isin(dates)
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        features_test = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument=benchmark_symbol,
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=dates,
            start=window.test_start,
            end=window.test_end,
            provenance="raw_forward_return",
            horizon=10,
        )
        returns_by_date = _return_map(returns_test)
        benchmark_by_date = _benchmark_map(benchmark)
        cache[window.label] = {
            "features_train": features_train,
            "returns_train": returns_train,
            "features_test": features_test,
        }

        for candidate in spec.candidates:
            candidate_id = candidate.candidate_id
            scores = _fit_scores(
                candidate,
                expressions_by_candidate[candidate_id],
                expression_columns,
                features_train,
                returns_train,
                features_test,
                window.label,
            )
            score_hashes[candidate_id][window.label] = _score_hash(scores)
            diagnostic = evaluate_candidate(
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
                    _score_frame(scores),
                    returns_by_date,
                    benchmark_by_date,
                    sectors,
                    cost_bps=cost_bps,
                    sector_cap=True,
                )
                selected = selections.loc[selections["challenger_selected"]]
                selected_sector_weight = (
                    float(selected.groupby(["period_index", "sector"]).size().max()) / TOP_N
                )
                metadata[candidate_id]["concentration"] = max(
                    float(metadata[candidate_id]["concentration"]),
                    selected_sector_weight,
                )
                observations.append(
                    {
                        "candidate_id": candidate_id,
                        "window": window.label,
                        "cost_bps": cost_bps,
                        "relative_excess": relative_excess(
                            float(result["total_return"]), float(result["benchmark_return"])
                        ),
                        "strategy_return": float(result["total_return"]),
                        "benchmark_return": float(result["benchmark_return"]),
                        "max_drawdown": float(result["max_drawdown"]),
                        "rank_ic": float(diagnostic["rank_ic"]),
                        "icir": float(diagnostic["icir"]),
                        "turnover": float(result["turnover"]),
                        "costs": float(result["costs"]),
                        "max_sector_weight": float(periods["max_sector_weight"].max()),
                    }
                )

    receipt = evaluate_experiment(spec.contract, observations, candidate_metadata=metadata)
    baseline_id = spec.contract.baseline_candidate_id
    support = _support_boundary(receipt, observations, baseline_id)
    leader_id = str(support["leader"])
    leader = next(item for item in spec.candidates if item.candidate_id == leader_id)

    reproduction: dict[str, dict[str, str]] = {}
    deterministic = True
    for window in windows:
        cached = cache[window.label]
        replay = _fit_scores(
            leader,
            expressions_by_candidate[leader_id],
            expression_columns,
            cached["features_train"],
            cached["returns_train"],
            cached["features_test"],
            window.label,
        )
        second = _score_hash(replay)
        first = score_hashes[leader_id][window.label]
        reproduction[window.label] = {"first": first, "second": second}
        deterministic = deterministic and first == second

    support["exact_score_reproduction"] = deterministic
    support["supported"] = bool(support["supported_before_determinism"] and deterministic)
    receipt.update(
        {
            "status": "completed",
            "runner": REPLAY_ID,
            "observed_provider_identity_sha256": observed_provider,
            "sector_classification_identity_sha256": sector_identity,
            "candidate_metadata": metadata,
            "support_boundary": support,
            "score_reproduction": reproduction,
            "stage_b_supported": bool(support["supported"]),
            "research_only": True,
            "trade_ready": False,
            "automatic_promotion": False,
        }
    )
    _write_json(output / "observations.json", observations)
    _write_json(output / "stage_b_receipt.json", receipt)
    return receipt
