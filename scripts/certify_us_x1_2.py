"""Certify the bounded US x1.2 candidates against the formal US x1.1 baseline.

Candidate ranking uses only the four consumed development windows (2024H1-2025H2).
2026H1 is reporting-only. The available 2026H2 partial window is a fresh challenge
and may veto, but never rank, the selected development winner.

Portfolio evaluation reuses the governed rank-aware sector-cap implementation so
transaction costs are charged from actual turnover rather than approximated by a
return multiplier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

import scripts.run_us_x1_1_native_xgb_grid as native_grid
import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
import scripts.run_us_x1_1_sector_style_attribution as attribution
from src.research.daily_ranker import prepare_ranker_frame
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

CONFIG = Path("configs/research_experiments/us_x1_2_certification_v1.yaml")
MODEL = Path("configs/models/us_x1_1.yaml")
UNIVERSE = Path("configs/research_universes/us_selected_equities_v2.yaml")
CLASSIFICATION = Path("configs/research_classifications/us87_sector_industry_v1.yaml")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
DEVELOPMENT_LABELS = ("2024H1", "2024H2", "2025H1", "2025H2")
COSTS = (20, 40, 60)


@dataclass(frozen=True)
class Candidate:
    model_id: str
    calibration: XGBNativeCalibration
    sector_cap_enabled: bool


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def _relative(strategy_return: float, benchmark_return: float) -> float:
    benchmark_nav = 1.0 + benchmark_return
    if benchmark_nav <= 0:
        raise ValueError("benchmark NAV must remain positive")
    return (1.0 + strategy_return) / benchmark_nav - 1.0


def _calibration(raw: dict[str, Any]) -> XGBNativeCalibration:
    return XGBNativeCalibration.from_dict(dict(raw))


def _candidates(config: dict[str, Any]) -> list[Candidate]:
    baseline = dict(config["baseline"])
    result = [
        Candidate(
            model_id="us_x1_1_effective_baseline",
            calibration=_calibration(dict(baseline["calibration"])),
            sector_cap_enabled=False,
        )
    ]
    for model_id, raw in dict(config["candidates"]).items():
        result.append(
            Candidate(
                model_id=str(model_id),
                calibration=_calibration(dict(raw["calibration"])),
                sector_cap_enabled=True,
            )
        )
    return result


def _resolve_symbols(runtime: QlibUSExecutionRuntime) -> list[str]:
    universe = _load_yaml(UNIVERSE)
    requested = [str(item) for item in universe.get("symbols", [])]
    expected = int(universe.get("candidate_count", len(requested)))
    if len(requested) != expected or len(requested) != len(set(requested)):
        raise ValueError("US universe contract is inconsistent")
    normalized = normalize_market_symbols(
        "us", requested, available_symbols=runtime.available_symbols()
    )
    symbols = [item.normalized_symbol for item in normalized]
    if len(symbols) != expected or len(symbols) != len(set(symbols)):
        raise ValueError("US universe normalization changed membership")
    return symbols


def _sector_map(symbols: list[str]) -> dict[str, str]:
    raw = _load_yaml(CLASSIFICATION)
    records = raw.get("records", {})
    mapping = {
        str(symbol): str(record["sector"])
        for symbol, record in dict(records).items()
        if isinstance(record, dict) and record.get("sector")
    }
    missing = sorted(set(symbols) - set(mapping))
    if missing:
        raise ValueError(f"missing governed sector labels: {missing}")
    return {symbol: mapping[symbol] for symbol in symbols}


def _window_sets(runtime: QlibUSExecutionRuntime) -> tuple[list[Any], dict[str, pd.DatetimeIndex]]:
    dev_calendar = runtime.calendar("2021-01-01", "2025-12-31")
    dev_end = min(pd.Timestamp("2025-12-31"), dev_calendar.max()).strftime("%Y-%m-%d")
    dev_plan = build_window_sampling_plan(
        dev_calendar,
        "2021-01-01",
        dev_end,
        first_test_year=2024,
        last_test_year=2025,
        min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    dev_windows = list(dev_plan.selected_windows)
    if tuple(window.label for window in dev_windows) != DEVELOPMENT_LABELS:
        raise ValueError(f"unexpected development windows: {[w.label for w in dev_windows]}")
    dates = horizon_eligible_dates_by_window(dev_plan, dev_calendar)

    current_calendar = runtime.calendar("2021-01-01", "2026-12-31")
    current_end = current_calendar.max().strftime("%Y-%m-%d")
    current_plan = build_window_sampling_plan(
        current_calendar,
        "2021-01-01",
        current_end,
        first_test_year=2026,
        last_test_year=2026,
        min_complete_windows=1,
        partial_window_policy="allow_horizon_contained_partial_final_window",
        min_partial_window_eligible_sessions=10,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    current_windows = list(current_plan.selected_windows)
    current_dates = horizon_eligible_dates_by_window(current_plan, current_calendar)
    report = [w for w in current_windows if pd.Timestamp(w.test_start) < pd.Timestamp("2026-07-01")]
    challenge = [w for w in current_windows if pd.Timestamp(w.test_start) >= pd.Timestamp("2026-07-01")]
    if len(report) != 1:
        raise ValueError(f"expected one 2026H1 reporting window, got {[w.label for w in report]}")
    if len(challenge) != 1:
        raise ValueError(
            "fresh 2026H2 challenge is unavailable or ambiguous: "
            f"{[w.label for w in challenge]}"
        )
    dates.update(current_dates)
    return dev_windows + report + challenge, dates


def _score_digest(scores: pd.DataFrame) -> str:
    ordered = scores.sort_index()
    body = ordered.to_csv(float_format="%.17g", lineterminator="\n")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _window_kind(window: Any) -> str:
    start = pd.Timestamp(window.test_start)
    if window.label in DEVELOPMENT_LABELS:
        return "development"
    if start < pd.Timestamp("2026-07-01"):
        return "reporting_only"
    return "fresh_challenge"


def _fit_scores(
    runtime: QlibUSExecutionRuntime,
    symbols: list[str],
    feature_expressions: list[str],
    window: Any,
    evaluation_dates: pd.DatetimeIndex,
    calibrations: dict[str, XGBNativeCalibration],
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    features_all = normalize_qlib_frame_index(
        runtime.features(symbols, feature_expressions, window.train_start, window.test_end)
    ).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [f"feature_{index}" for index in range(len(feature_expressions))]
    returns_all = normalize_qlib_frame_index(
        runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
    )
    returns_all.columns = ["return"]
    returns_all.attrs.update(
        {"provenance": "raw_forward_return", "horizon": 10, "expression": RETURN_EXPRESSION}
    )
    dates = features_all.index.get_level_values("datetime")
    train_mask = (dates >= pd.Timestamp(window.train_start)) & (dates <= pd.Timestamp(window.train_end))
    test_mask = dates.isin(evaluation_dates)
    train_features, train_returns = purge_training_tail(
        features_all.loc[train_mask].copy(), returns_all.loc[train_mask].copy(), holding_days=10
    )
    valid, reason = validate_no_nan_inputs(
        train_features, context=f"US x1.2 certification/{window.label}"
    )
    if not valid:
        raise ValueError(reason)
    test_features = features_all.loc[test_mask].copy()
    test_returns = returns_all.loc[test_mask].copy()
    test_returns.attrs.update(returns_all.attrs)
    x_rank, y_rank, groups = prepare_ranker_frame(train_features, train_returns)
    scores: dict[str, pd.DataFrame] = {}
    for calibration_id, calibration in calibrations.items():
        fitted = fit_xgb_native_daily_ranker(
            x_rank, y_rank, groups, calibration=calibration
        )
        scores[calibration_id] = predict_xgb_native_daily_ranker(fitted, test_features)
    return scores, test_returns, test_features


def _evaluate_window(
    runtime: QlibUSExecutionRuntime,
    symbols: list[str],
    sectors: dict[str, str],
    feature_expressions: list[str],
    window: Any,
    evaluation_dates: pd.DatetimeIndex,
    candidates: list[Candidate],
) -> dict[str, Any]:
    unique_calibrations: dict[str, XGBNativeCalibration] = {}
    calibration_key_by_model: dict[str, str] = {}
    identity_to_key: dict[str, str] = {}
    for candidate in candidates:
        identity = str(candidate.calibration.identity_manifest()["identity_sha256"])
        key = identity_to_key.setdefault(identity, candidate.model_id)
        unique_calibrations.setdefault(key, candidate.calibration)
        calibration_key_by_model[candidate.model_id] = key

    scores_by_key, test_returns, _ = _fit_scores(
        runtime,
        symbols,
        feature_expressions,
        window,
        evaluation_dates,
        unique_calibrations,
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
    market_returns, benchmark_map, _, _ = attribution._market_data(
        runtime,
        symbols,
        evaluation_dates.min(),
        evaluation_dates.max(),
    )

    model_rows: dict[str, Any] = {}
    for candidate in candidates:
        scores = scores_by_key[calibration_key_by_model[candidate.model_id]]
        score_quality = native_grid._stress_result(
            scores, test_returns, benchmark, cost_bps=20
        )
        reset_scores = scores.reset_index()
        costs: dict[str, Any] = {}
        for cost in COSTS:
            result, _, _, selections, _ = sector_cap._evaluate(
                reset_scores,
                market_returns,
                benchmark_map,
                sectors,
                cost_bps=cost,
                sector_cap=candidate.sector_cap_enabled,
            )
            relative = _relative(
                float(result["total_return"]), float(result["benchmark_return"])
            )
            selected = selections.loc[selections["challenger_selected"]]
            max_sector_names = int(
                selected.groupby(["period_index", "sector"]).size().max()
            )
            costs[str(cost)] = {
                **result,
                "relative_excess": relative,
                "max_sector_names": max_sector_names,
            }
        model_rows[candidate.model_id] = {
            "model_id": candidate.model_id,
            "sector_cap_enabled": candidate.sector_cap_enabled,
            "calibration_identity": candidate.calibration.identity_manifest(),
            "score_digest": _score_digest(scores),
            "score_quality": {
                "ic": float(score_quality.get("ic", 0.0)),
                "icir": float(score_quality.get("icir", 0.0)),
                "rank_ic": float(score_quality.get("rank_ic", 0.0)),
                "top_bottom_spread": float(
                    dict(score_quality.get("score_direction", {})).get(
                        "top_minus_bottom_spread", 0.0
                    )
                ),
            },
            "costs": costs,
        }
    return {
        "window": window.label,
        "kind": _window_kind(window),
        "train_start": str(window.train_start),
        "train_end": str(window.train_end),
        "test_start": evaluation_dates.min().strftime("%Y-%m-%d"),
        "test_end": evaluation_dates.max().strftime("%Y-%m-%d"),
        "eligible_dates": int(len(evaluation_dates)),
        "models": model_rows,
    }


def _aggregate(model_id: str, windows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row["models"][model_id] for row in windows]
    result: dict[str, Any] = {"model_id": model_id}
    for cost in COSTS:
        cost_rows = [row["costs"][str(cost)] for row in rows]
        strategy = _compound([float(row["total_return"]) for row in cost_rows])
        benchmark = _compound([float(row["benchmark_return"]) for row in cost_rows])
        result[f"strategy_return_{cost}bps"] = strategy
        result[f"benchmark_return_{cost}bps"] = benchmark
        result[f"relative_excess_{cost}bps"] = _relative(strategy, benchmark)
        result[f"turnover_{cost}bps"] = float(sum(float(row["turnover"]) for row in cost_rows))
        result[f"costs_{cost}bps"] = float(sum(float(row["costs"]) for row in cost_rows))
    relative_windows = [float(row["costs"]["20"]["relative_excess"]) for row in rows]
    positive = [value for value in relative_windows if value > 0]
    result.update(
        {
            "positive_windows": int(sum(value > 0 for value in relative_windows)),
            "worst_drawdown_20bps": min(
                float(row["costs"]["20"]["max_drawdown"]) for row in rows
            ),
            "strongest_positive_window_share": (
                max(positive) / sum(positive) if positive else 1.0
            ),
            "mean_icir": float(np.mean([row["score_quality"]["icir"] for row in rows])),
            "mean_rank_ic": float(
                np.mean([row["score_quality"]["rank_ic"] for row in rows])
            ),
            "mean_top_bottom_spread": float(
                np.mean([row["score_quality"]["top_bottom_spread"] for row in rows])
            ),
            "per_window": {
                window["window"]: {
                    "relative_excess_20bps": float(
                        window["models"][model_id]["costs"]["20"]["relative_excess"]
                    ),
                    "relative_excess_60bps": float(
                        window["models"][model_id]["costs"]["60"]["relative_excess"]
                    ),
                    "max_drawdown_20bps": float(
                        window["models"][model_id]["costs"]["20"]["max_drawdown"]
                    ),
                    "turnover_20bps": float(
                        window["models"][model_id]["costs"]["20"]["turnover"]
                    ),
                }
                for window in windows
            },
        }
    )
    return result


def _development_decision(
    aggregates: dict[str, dict[str, Any]], baseline_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    baseline = aggregates[baseline_id]
    baseline_relative = float(baseline["relative_excess_20bps"])
    baseline_dd = float(baseline["worst_drawdown_20bps"])
    baseline_rank_ic = float(baseline["mean_rank_ic"])
    evaluated: list[dict[str, Any]] = []
    for model_id, row in aggregates.items():
        if model_id == baseline_id:
            continue
        gates = {
            "four_positive_relative_excess_windows": int(row["positive_windows"]) == 4,
            "positive_60bps_compounded_relative_excess": float(
                row["relative_excess_60bps"]
            )
            > 0,
            "retain_at_least_90pct_baseline_relative_excess": float(
                row["relative_excess_20bps"]
            )
            >= 0.90 * baseline_relative,
            "drawdown_improves_3pp_or_stays_above_minus_22pct": (
                float(row["worst_drawdown_20bps"]) >= baseline_dd + 0.03
                or float(row["worst_drawdown_20bps"]) >= -0.22
            ),
            "mean_rank_ic_not_materially_weaker_than_baseline": float(
                row["mean_rank_ic"]
            )
            >= max(0.0, baseline_rank_ic - 0.005),
            "strongest_positive_window_share_below_55pct": float(
                row["strongest_positive_window_share"]
            )
            < 0.55,
        }
        penalty = max(0.0, -float(row["worst_drawdown_20bps"]) - 0.22)
        selection_score = (
            float(row["relative_excess_20bps"])
            - 1.5 * penalty
            + 0.15 * float(row["mean_icir"])
            + 0.10 * float(row["mean_rank_ic"])
            + 0.10 * (1.0 - float(row["strongest_positive_window_share"]))
        )
        evaluated.append(
            {
                "model_id": model_id,
                "gates": gates,
                "all_gates_pass": all(gates.values()),
                "selection_score": selection_score,
                "drawdown_improvement": float(row["worst_drawdown_20bps"]) - baseline_dd,
                "relative_excess_improvement": float(row["relative_excess_20bps"])
                - baseline_relative,
            }
        )
    supported = sorted(
        [row for row in evaluated if row["all_gates_pass"]],
        key=lambda row: float(row["selection_score"]),
        reverse=True,
    )
    return evaluated, (str(supported[0]["model_id"]) if supported else None)


def _challenge_decision(
    selected_id: str | None,
    challenge_window: dict[str, Any],
    baseline_id: str,
) -> dict[str, Any]:
    if selected_id is None:
        return {
            "available": True,
            "selected_model_id": None,
            "gates": {},
            "all_gates_pass": False,
        }
    selected = challenge_window["models"][selected_id]
    baseline = challenge_window["models"][baseline_id]
    c20 = selected["costs"]["20"]
    c60 = selected["costs"]["60"]
    b20 = baseline["costs"]["20"]
    gates = {
        "challenge_window_exists": int(challenge_window["eligible_dates"]) >= 10,
        "positive_20bps_relative_excess": float(c20["relative_excess"]) > 0,
        "positive_60bps_relative_excess": float(c60["relative_excess"]) > 0,
        "drawdown_not_more_than_2pp_worse_than_baseline": float(c20["max_drawdown"])
        >= float(b20["max_drawdown"]) - 0.02,
    }
    return {
        "available": True,
        "selected_model_id": selected_id,
        "window": challenge_window["window"],
        "test_start": challenge_window["test_start"],
        "test_end": challenge_window["test_end"],
        "eligible_dates": challenge_window["eligible_dates"],
        "candidate_relative_excess_20bps": float(c20["relative_excess"]),
        "candidate_relative_excess_60bps": float(c60["relative_excess"]),
        "candidate_max_drawdown_20bps": float(c20["max_drawdown"]),
        "baseline_relative_excess_20bps": float(b20["relative_excess"]),
        "baseline_max_drawdown_20bps": float(b20["max_drawdown"]),
        "gates": gates,
        "all_gates_pass": all(gates.values()),
    }


def run(root: Path, *, provider_uri: Path, output_dir: Path) -> dict[str, Any]:
    root = root.resolve()
    provider_uri = provider_uri.resolve()
    output_dir = output_dir.resolve()
    config = _load_yaml(root / CONFIG)
    model = _load_yaml(root / MODEL)
    candidates = _candidates(config)
    baseline_id = "us_x1_1_effective_baseline"
    feature_expressions = [str(item) for item in model["features"]["expressions"]]

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    runtime_meta = runtime.metadata()
    symbols = _resolve_symbols(runtime)
    sectors = _sector_map(symbols)
    windows, dates_by_label = _window_sets(runtime)

    results: list[dict[str, Any]] = []
    for window in windows:
        evaluation_dates = dates_by_label[window.label]
        if len(evaluation_dates) < 10:
            raise ValueError(f"{window.label}: fewer than 10 horizon-contained dates")
        print(
            f"certify {window.label} kind={_window_kind(window)} "
            f"train={window.train_start}..{window.train_end} "
            f"test={evaluation_dates.min().date()}..{evaluation_dates.max().date()}"
        )
        results.append(
            _evaluate_window(
                runtime,
                symbols,
                sectors,
                feature_expressions,
                window,
                evaluation_dates,
                candidates,
            )
        )

    development = [row for row in results if row["kind"] == "development"]
    reporting = [row for row in results if row["kind"] == "reporting_only"]
    challenges = [row for row in results if row["kind"] == "fresh_challenge"]
    if len(development) != 4 or len(reporting) != 1 or len(challenges) != 1:
        raise ValueError("certification window partition is incomplete")

    aggregates = {
        candidate.model_id: _aggregate(candidate.model_id, development)
        for candidate in candidates
    }
    gate_results, selected_id = _development_decision(aggregates, baseline_id)
    challenge = _challenge_decision(selected_id, challenges[0], baseline_id)

    deterministic = False
    deterministic_checks: dict[str, Any] = {}
    if selected_id is not None:
        selected = next(candidate for candidate in candidates if candidate.model_id == selected_id)
        repeated_candidate = [selected]
        repeat_rows = []
        for window in windows:
            repeat_rows.append(
                _evaluate_window(
                    runtime,
                    symbols,
                    sectors,
                    feature_expressions,
                    window,
                    dates_by_label[window.label],
                    repeated_candidate,
                )
            )
        first_digests = {
            row["window"]: row["models"][selected_id]["score_digest"] for row in results
        }
        repeat_digests = {
            row["window"]: row["models"][selected_id]["score_digest"]
            for row in repeat_rows
        }
        deterministic = first_digests == repeat_digests
        deterministic_checks = {
            "first_score_digests": first_digests,
            "repeat_score_digests": repeat_digests,
            "exact": deterministic,
        }

    promotion_supported = bool(
        selected_id is not None and challenge["all_gates_pass"] and deterministic
    )
    reporting_summary = {
        candidate.model_id: {
            "relative_excess_20bps": float(
                reporting[0]["models"][candidate.model_id]["costs"]["20"]["relative_excess"]
            ),
            "relative_excess_60bps": float(
                reporting[0]["models"][candidate.model_id]["costs"]["60"]["relative_excess"]
            ),
            "max_drawdown_20bps": float(
                reporting[0]["models"][candidate.model_id]["costs"]["20"]["max_drawdown"]
            ),
        }
        for candidate in candidates
    }
    payload = {
        "schema_version": "1.0",
        "experiment_id": str(config["experiment_id"]),
        "parent_model_id": "us_x1_1",
        "target_model_id": "us_x1_2",
        "provider": {
            "provider_uri": provider_uri.as_posix(),
            "identity_sha256": str(runtime_meta.get("provider_identity_sha256", "")),
            "calendar_end": runtime.calendar("2021-01-01", "2026-12-31").max().strftime(
                "%Y-%m-%d"
            ),
        },
        "universe_count": len(symbols),
        "development_aggregates": aggregates,
        "development_gate_results": gate_results,
        "selected_development_winner": selected_id,
        "reporting_2026H1": reporting_summary,
        "fresh_challenge": challenge,
        "determinism": deterministic_checks,
        "promotion_supported": promotion_supported,
        "promotion_decision": (
            "promote_selected_winner_to_us_x1_2"
            if promotion_supported
            else "retain_us_x1_1"
        ),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output_dir / "us_x1_2_certification.json", payload)
    compact = {
        "selected": selected_id,
        "promotion_supported": promotion_supported,
        "development": {
            key: {
                "relative_excess_20bps": value["relative_excess_20bps"],
                "relative_excess_60bps": value["relative_excess_60bps"],
                "worst_drawdown_20bps": value["worst_drawdown_20bps"],
                "mean_rank_ic": value["mean_rank_ic"],
            }
            for key, value in aggregates.items()
        },
        "reporting_2026H1": reporting_summary.get(selected_id, {}) if selected_id else {},
        "fresh_challenge": challenge,
        "deterministic": deterministic,
    }
    print("US_X1_2_CERTIFICATION=" + json.dumps(compact, sort_keys=True, allow_nan=False))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_2_certification_v1"),
    )
    args = parser.parse_args()
    run(args.root, provider_uri=args.provider_uri, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
