"""Reproduce US x1.1 twice on one frozen deterministic provider.

The runner owns no model search. It fits the exact effective US x1.1 contract
independently twice for each 2024H1--2025H2 development window, hashes complete
scores, ranks and Top-15 ledgers, and requires identical economics. Canonical
US x1.1 evidence is used only for a bounded data-revision comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_us_x1_1_native_xgb_grid import (
    BASELINE_ID,
    DECISION_WINDOWS,
    EXPERIMENT_CONFIG,
    MODEL_CONFIG,
    RETURN_EXPRESSION,
    UNIVERSE_CONFIG,
    _load_yaml,
    _native_calibrations,
    _resolve_symbols,
    _stress_result,
)
from src.research.daily_ranker import prepare_ranker_frame
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
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

EXPERIMENT_ID = "us_x1_1_deterministic_reproduction_v1"
EXPECTED_PROVIDER = "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
COST_STRESS_BPS = (20, 40, 60)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _score_ledger(scores: pd.DataFrame) -> pd.DataFrame:
    if list(scores.columns) != ["score"]:
        raise ValueError("score frame must contain one score column")
    if not isinstance(scores.index, pd.MultiIndex):
        raise ValueError("score frame must use a MultiIndex")
    frame = scores.reset_index()
    required = {"datetime", "instrument", "score"}
    if not required.issubset(frame.columns):
        raise ValueError(f"score frame is missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if not np.isfinite(frame["score"].to_numpy(dtype=float)).all():
        raise ValueError("score frame contains non-finite values")
    return frame.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(
        drop=True
    )


def _rank_ledger(score_ledger: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for date, group in score_ledger.groupby("datetime", sort=True):
        ordered = group.sort_values(
            ["score", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).copy()
        ordered["rank"] = np.arange(1, len(ordered) + 1, dtype=int)
        ordered["datetime"] = date
        rows.append(ordered.loc[:, ["datetime", "instrument", "score", "rank"]])
    if not rows:
        raise ValueError("rank ledger cannot be empty")
    return pd.concat(rows, ignore_index=True)


def _selection_ledger(rank_ledger: pd.DataFrame, *, topk: int = 15) -> pd.DataFrame:
    selected = rank_ledger.loc[rank_ledger["rank"] <= topk].copy()
    selected["target_weight"] = 1.0 / float(topk)
    return selected.loc[
        :, ["datetime", "instrument", "score", "rank", "target_weight"]
    ].reset_index(drop=True)


def _ledger_bytes(frame: pd.DataFrame) -> bytes:
    output = frame.copy()
    output["datetime"] = pd.to_datetime(output["datetime"]).dt.strftime("%Y-%m-%d")
    return output.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.17g",
    ).encode("utf-8")


def _write_ledger(path: Path, frame: pd.DataFrame) -> str:
    payload = _ledger_bytes(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _compound(values: list[float]) -> float:
    return math.prod(1.0 + value for value in values) - 1.0


def _relative(strategy: float, benchmark: float) -> float:
    return (1.0 + strategy) / (1.0 + benchmark) - 1.0


def _aggregate(window_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(window_rows, key=lambda item: DECISION_WINDOWS.index(item["window"]))
    costs: dict[str, Any] = {}
    for cost in COST_STRESS_BPS:
        metrics = [dict(row["cost_stress"][str(cost)]) for row in ordered]
        strategy = _compound([float(item["total_return"]) for item in metrics])
        benchmark = _compound([float(item["benchmark_return"]) for item in metrics])
        costs[str(cost)] = {
            "compounded_strategy_return": strategy,
            "compounded_benchmark_return": benchmark,
            "compounded_relative_excess_return": _relative(strategy, benchmark),
        }
    base = [dict(row["cost_stress"]["20"]) for row in ordered]
    recurring = set(str(value) for value in base[0].get("top_selected_stocks", []))
    for row in base[1:]:
        recurring &= set(str(value) for value in row.get("top_selected_stocks", []))
    positive = [float(row["excess_return"]) for row in base if float(row["excess_return"]) > 0]
    return {
        "n_windows": len(ordered),
        "positive_excess_windows": sum(float(row["excess_return"]) > 0 for row in base),
        "mean_icir": float(np.mean([float(row["icir"]) for row in base])),
        "mean_rank_ic": float(np.mean([float(row["rank_ic"]) for row in base])),
        "mean_spread": float(
            np.mean(
                [
                    float(row["score_direction"]["top_minus_bottom_spread"])
                    for row in base
                ]
            )
        ),
        "worst_drawdown": min(float(row["max_drawdown"]) for row in base),
        "strongest_positive_window_share": (
            max(positive) / sum(positive) if positive else 1.0
        ),
        "all_window_recurring_names": sorted(recurring),
        "cost_stress": costs,
        "windows": ordered,
    }


def _canonical_comparison(model: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(model["backtest_evidence"]["development"])
    canonical_windows = {
        str(row["window"]): dict(row) for row in canonical.get("windows", [])
    }
    revision_windows = {
        str(row["window"]): dict(row["cost_stress"]["20"])
        for row in revision["windows"]
    }
    window_rows: list[dict[str, Any]] = []
    for window in DECISION_WINDOWS:
        old = canonical_windows[window]
        new = revision_windows[window]
        window_rows.append(
            {
                "window": window,
                "canonical": {
                    "total_return": float(old["total_return"]),
                    "benchmark_return": float(old["benchmark_return"]),
                    "simple_excess": float(old["simple_excess"]),
                    "icir": float(old["icir"]),
                    "rank_ic": float(old["rank_ic"]),
                    "max_drawdown": float(old["max_drawdown"]),
                    "turnover": float(old["turnover"]),
                },
                "revision": {
                    "total_return": float(new["total_return"]),
                    "benchmark_return": float(new["benchmark_return"]),
                    "simple_excess": float(new["excess_return"]),
                    "icir": float(new["icir"]),
                    "rank_ic": float(new["rank_ic"]),
                    "max_drawdown": float(new["max_drawdown"]),
                    "turnover": float(new["turnover"]),
                },
                "delta": {
                    "total_return": float(new["total_return"]) - float(old["total_return"]),
                    "benchmark_return": float(new["benchmark_return"])
                    - float(old["benchmark_return"]),
                    "simple_excess": float(new["excess_return"])
                    - float(old["simple_excess"]),
                    "max_drawdown": float(new["max_drawdown"])
                    - float(old["max_drawdown"]),
                    "turnover": float(new["turnover"]) - float(old["turnover"]),
                },
                "canonical_final_top15": list(old.get("top_selected_stocks", [])),
                "revision_final_top15": list(new.get("top_selected_stocks", [])),
            }
        )
    canonical_relative = float(canonical["compounded_relative_excess_return"])
    revision_relative = float(
        revision["cost_stress"]["20"]["compounded_relative_excess_return"]
    )
    return {
        "canonical_provider_identity": model["provider_binding"][
            "canonical_evidence_provider_identity_sha256"
        ],
        "revision_provider_identity": EXPECTED_PROVIDER,
        "canonical_compounded_relative_excess": canonical_relative,
        "revision_compounded_relative_excess": revision_relative,
        "relative_excess_delta": revision_relative - canonical_relative,
        "canonical_worst_drawdown": float(canonical["worst_drawdown"]),
        "revision_worst_drawdown": float(revision["worst_drawdown"]),
        "worst_drawdown_delta": float(revision["worst_drawdown"])
        - float(canonical["worst_drawdown"]),
        "canonical_recurring_names": list(canonical["all_window_recurring_names"]),
        "revision_recurring_names": list(revision["all_window_recurring_names"]),
        "window_comparison": window_rows,
        "score_rank_correlation_available": False,
        "full_selection_overlap_available": False,
        "limitation": (
            "The canonical artifact/model card does not retain complete score and "
            "per-rebalance selection ledgers. Metrics and final-window selections "
            "can be compared; full score-rank correlation cannot be reconstructed."
        ),
    }


def run(
    root: Path,
    *,
    provider_uri: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    provider_uri = provider_uri.resolve()
    output_dir = output_dir.resolve()
    model = _load_yaml(root / MODEL_CONFIG)
    experiment = _load_yaml(root / EXPERIMENT_CONFIG)
    universe = _load_yaml(root / UNIVERSE_CONFIG)
    calibration = dict(_native_calibrations(experiment))[BASELINE_ID]
    parameter_manifest = calibration.identity_manifest()
    features = [str(value) for value in model["features"]["expressions"]]

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri)
    runtime.initialize(root)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if observed_provider != EXPECTED_PROVIDER:
        raise ValueError(
            f"unexpected deterministic provider: {observed_provider}; expected {EXPECTED_PROVIDER}"
        )
    symbols = _resolve_symbols(runtime, universe)
    calendar = runtime.calendar("2021-01-01", "2025-12-31")
    available_end = min(pd.Timestamp("2025-12-31"), calendar.max()).strftime("%Y-%m-%d")
    plan = build_window_sampling_plan(
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
    windows = list(plan.selected_windows)
    if tuple(window.label for window in windows) != DECISION_WINDOWS:
        raise ValueError(f"unexpected windows: {[window.label for window in windows]}")
    eligible_dates = horizon_eligible_dates_by_window(plan, calendar)

    rows_by_run: dict[str, list[dict[str, Any]]] = {"a": [], "b": []}
    determinism: list[dict[str, Any]] = []
    for window in windows:
        dates = eligible_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, features, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [f"feature_{index}" for index in range(len(features))]
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
        all_dates = features_all.index.get_level_values("datetime")
        train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
            all_dates <= pd.Timestamp(window.train_end)
        )
        test_mask = all_dates.isin(dates)
        train_features, train_returns = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        valid, reason = validate_no_nan_inputs(
            train_features,
            context=f"US x1.1 deterministic reproduction/{window.label}",
        )
        if not valid:
            raise ValueError(reason)
        test_features = features_all.loc[test_mask].copy()
        test_returns = returns_all.loc[test_mask].copy()
        test_returns.attrs.update(returns_all.attrs)
        x_rank, y_rank, groups = prepare_ranker_frame(train_features, train_returns)
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument="QQQ",
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=dates,
            start=dates.min().strftime("%Y-%m-%d"),
            end=dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return",
            horizon=10,
        )

        window_hashes: dict[str, Any] = {}
        for run_id in ("a", "b"):
            fitted = fit_xgb_native_daily_ranker(
                x_rank,
                y_rank,
                groups,
                calibration=calibration,
            )
            scores = predict_xgb_native_daily_ranker(fitted, test_features)
            score_ledger = _score_ledger(scores)
            rank_ledger = _rank_ledger(score_ledger)
            selection_ledger = _selection_ledger(rank_ledger)
            ledger_root = output_dir / "ledgers" / run_id / window.label
            score_hash = _write_ledger(ledger_root / "scores.csv", score_ledger)
            rank_hash = _write_ledger(ledger_root / "ranks.csv", rank_ledger)
            selection_hash = _write_ledger(
                ledger_root / "top15_selections.csv", selection_ledger
            )
            cost_stress = {
                str(cost): _stress_result(
                    scores,
                    test_returns,
                    benchmark,
                    cost_bps=cost,
                )
                for cost in COST_STRESS_BPS
            }
            row = {
                "window": window.label,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "test_start": dates.min().strftime("%Y-%m-%d"),
                "test_end": dates.max().strftime("%Y-%m-%d"),
                "parameter_identity_sha256": parameter_manifest["identity_sha256"],
                "score_sha256": score_hash,
                "rank_sha256": rank_hash,
                "top15_selection_sha256": selection_hash,
                "raw_return_identity_sha256": _canonical_json_hash(
                    {
                        "expression": RETURN_EXPRESSION,
                        "index": [
                            [str(date), str(instrument)]
                            for date, instrument in test_returns.index.tolist()
                        ],
                        "values": [
                            format(float(value), ".17g")
                            for value in test_returns["return"].to_numpy(dtype=float)
                        ],
                    }
                ),
                "cost_stress": cost_stress,
                "metrics_sha256": _canonical_json_hash(cost_stress),
            }
            rows_by_run[run_id].append(row)
            window_hashes[run_id] = {
                key: row[key]
                for key in (
                    "parameter_identity_sha256",
                    "score_sha256",
                    "rank_sha256",
                    "top15_selection_sha256",
                    "raw_return_identity_sha256",
                    "metrics_sha256",
                )
            }
        matches = window_hashes["a"] == window_hashes["b"]
        determinism.append(
            {
                "window": window.label,
                "run_a": window_hashes["a"],
                "run_b": window_hashes["b"],
                "all_identities_match": matches,
            }
        )

    aggregate_a = _aggregate(rows_by_run["a"])
    aggregate_b = _aggregate(rows_by_run["b"])
    aggregate_match = _canonical_json_hash(aggregate_a) == _canonical_json_hash(aggregate_b)
    deterministic = all(item["all_identities_match"] for item in determinism) and aggregate_match
    comparison = _canonical_comparison(model, aggregate_a)
    if not deterministic:
        decision = "model_input_identity_not_reproducible"
    else:
        decision = "us_x1_1_deterministic_on_revision_provider"

    payload = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "issue": 393,
        "parent_model_id": "us_x1_1",
        "research_only": True,
        "trade_ready": False,
        "provider": {
            "observed_identity_sha256": observed_provider,
            "expected_identity_sha256": EXPECTED_PROVIDER,
            "matches_expected": observed_provider == EXPECTED_PROVIDER,
        },
        "parameter_identity": parameter_manifest,
        "decision_windows": list(DECISION_WINDOWS),
        "consumed_reporting_windows_excluded": ["2026H1"],
        "run_a": aggregate_a,
        "run_b": aggregate_b,
        "window_determinism": determinism,
        "aggregate_identity_match": aggregate_match,
        "canonical_comparison": comparison,
        "decision": {
            "decision": decision,
            "deterministic_on_revision_provider": deterministic,
            "automatic_model_update": False,
            "creates_us_x1_2_candidate": False,
            "data_migration_only": True,
            "canonical_full_score_comparison_available": False,
        },
    }
    _write_json(output_dir / "deterministic_reproduction.json", payload)
    _write_json(
        output_dir / "run_identity_manifest.json",
        {
            "schema_version": "1.0",
            "experiment_id": EXPERIMENT_ID,
            "provider_identity_sha256": observed_provider,
            "parameter_identity": parameter_manifest,
            "window_determinism": determinism,
            "aggregate_a_sha256": _canonical_json_hash(aggregate_a),
            "aggregate_b_sha256": _canonical_json_hash(aggregate_b),
            "decision": decision,
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
        default=Path("artifacts/evidence/us_x1_1_deterministic_reproduction_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
