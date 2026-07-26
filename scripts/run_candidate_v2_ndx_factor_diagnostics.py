"""Diagnose why candidate_v2 broad IC does not reach the NDX Top-3 tail.

This runner does not tune or train a new candidate.  It binds to the existing
four-window candidate_v2 NDX evidence, reloads the seven frozen input factors
for the exact OOS symbols and dates, and compares:

* broad daily Pearson IC and Rank IC;
* exact rebalance-date Top-3/Bottom-3, Top-10/Bottom-10, and
  Top-20/Bottom-20 raw 10D-return spreads;
* original and inverted descriptive orientations; and
* direction and tail stability across all four OOS windows.

All economic diagnostics use canonical raw 10D forward returns.  Any
orientation that looks best in this OOS evidence is descriptive only and
cannot be promoted without a new, untouched validation period.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_candidate_v2_universe_robustness import (
    FROZEN_CALIBRATION,
    FROZEN_FEATURE_GROUP,
    FROZEN_TOP_N,
    _normalize_index,
    _verify_us_provider,
)
from src.research.cross_sectional_factor_diagnostics import (
    diagnose_cross_sectional_score,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR

SCHEMA_VERSION = "1.0"
REQUIRED_WINDOWS = 4
TAIL_SIZES = (3, 10, 20)
LIGHTGBM_DEFAULT_LAMBDARANK_TRUNCATION_LEVEL = 30
DIAGNOSTIC_CONSISTENCY_THRESHOLDS: dict[str, float] = {
    "min_mean_daily_rank_ic": 0.0,
    "min_mean_daily_rank_icir": 0.0,
    "min_positive_daily_rank_ic_window_ratio": 0.75,
    "min_mean_daily_quintile_spread": 0.0,
    "min_positive_daily_quintile_spread_window_ratio": 0.75,
    "min_rebalance_top3_spread": 0.0,
    "min_positive_rebalance_top3_window_ratio": 0.75,
    "min_positive_rebalance_top3_period_ratio": 0.55,
}
DEFAULT_SOURCE_DIR = Path("artifacts/evidence/candidate_v2_ndx_window_start")
DEFAULT_OUTPUT_DIR = Path("artifacts/evidence/candidate_v2_ndx_factor_diagnostics")

FROZEN_FACTOR_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "feature:momentum_5d",
        "family": "momentum",
        "expression": "$close/Ref($close,5)-1",
    },
    {
        "id": "feature:momentum_10d",
        "family": "momentum",
        "expression": "$close/Ref($close,10)-1",
    },
    {
        "id": "feature:momentum_20d",
        "family": "momentum",
        "expression": "$close/Ref($close,20)-1",
    },
    {
        "id": "feature:volatility_10d",
        "family": "volatility",
        "expression": "Std($close/Ref($close,1)-1,10)",
    },
    {
        "id": "feature:volatility_20d",
        "family": "volatility",
        "expression": "Std($close/Ref($close,1)-1,20)",
    },
    {
        "id": "feature:volume_momentum_10d",
        "family": "volume",
        "expression": "$volume/Ref($volume,10)-1",
    },
    {
        "id": "feature:volume_vs_mean_20d",
        "family": "volume",
        "expression": "$volume/Mean($volume,20)-1",
    },
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _validate_frozen_factor_contract() -> None:
    declared = tuple(item["expression"] for item in FROZEN_FACTOR_DEFINITIONS)
    if declared != FROZEN_FEATURE_GROUP.expressions:
        raise ValueError("diagnostic factor definitions drifted from frozen candidate_v2 features")
    ids = [item["id"] for item in FROZEN_FACTOR_DEFINITIONS]
    if len(ids) != len(set(ids)):
        raise ValueError("diagnostic factor ids must be unique")


def _load_source_evidence(
    source_dir: Path,
    *,
    provider_identity: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    manifest_path = source_dir / "evidence_manifest.json"
    aggregate_path = source_dir / "aggregate.json"
    manifest = _read_json(manifest_path)
    aggregate_wrapper = _read_json(aggregate_path)
    aggregate = aggregate_wrapper.get("aggregate")
    if not isinstance(aggregate, dict):
        raise ValueError("source aggregate is missing its aggregate payload")

    if manifest.get("provider_identity_sha256") != provider_identity:
        raise ValueError("source evidence provider identity does not match data provider")
    if manifest.get("research_only") is not True:
        raise ValueError("source evidence must be research_only")
    if manifest.get("promotion_eligible") is not False:
        raise ValueError("source evidence must not be promotion eligible")
    if manifest.get("trade_ready") is not False:
        raise ValueError("source evidence must not be trade ready")
    if manifest.get("training_membership_asof_semiannual") is not True:
        raise ValueError("source evidence must use semiannual as-of training membership")
    if manifest.get("training_uses_future_oos_snapshot") is not False:
        raise ValueError("source evidence cannot use a future OOS snapshot for training")
    if aggregate.get("n_windows_evaluated") != REQUIRED_WINDOWS:
        raise ValueError(f"source evidence must contain {REQUIRED_WINDOWS} evaluated windows")

    window_paths = sorted((source_dir / "per_window").glob("*.json"))
    if len(window_paths) != REQUIRED_WINDOWS:
        raise ValueError(f"source evidence must contain {REQUIRED_WINDOWS} per-window files")
    windows = [_read_json(path) for path in window_paths]
    labels = [str(payload.get("window", {}).get("label", "")) for payload in windows]
    if len(set(labels)) != REQUIRED_WINDOWS or any(not label for label in labels):
        raise ValueError("source evidence window labels must be unique and non-empty")
    for payload in windows:
        if payload.get("skipped") is True:
            raise ValueError("source evidence contains a skipped window")
        coverage = payload.get("coverage_meta")
        if not isinstance(coverage, dict):
            raise ValueError("source window is missing coverage_meta")
        if coverage.get("oos_membership_point_in_time") is not True:
            raise ValueError("source window must freeze OOS membership at window start")
        if coverage.get("training_uses_future_oos_snapshot") is not False:
            raise ValueError("source window training cannot use future OOS membership")

    hashes = {
        str(path.relative_to(source_dir)).replace("\\", "/"): _sha256_file(path)
        for path in [manifest_path, aggregate_path, *window_paths]
    }
    return manifest, aggregate, windows, hashes


def _finite_mean(values: list[Any]) -> float | None:
    finite = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and np.isfinite(float(value))
    ]
    return float(np.mean(finite)) if finite else None


def _positive_ratio(values: list[Any]) -> float | None:
    finite = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and np.isfinite(float(value))
    ]
    return float(np.mean([value > 0.0 for value in finite])) if finite else None


def _greater(value: Any, threshold: float) -> bool:
    return bool(
        isinstance(value, (int, float)) and np.isfinite(float(value)) and float(value) > threshold
    )


def _at_least(value: Any, threshold: float) -> bool:
    return bool(
        isinstance(value, (int, float)) and np.isfinite(float(value)) and float(value) >= threshold
    )


def _orientation_aggregate(
    factor_windows: list[dict[str, Any]],
    orientation: str,
) -> dict[str, Any]:
    daily = [
        window["diagnostic"]["orientations"][orientation]["daily"] for window in factor_windows
    ]
    rebalance = [
        window["diagnostic"]["orientations"][orientation]["rebalance"] for window in factor_windows
    ]
    fixed_tails: dict[str, Any] = {}
    for size in TAIL_SIZES:
        key = str(size)
        rows = [item["fixed_tails"][key] for item in rebalance]
        fixed_tails[key] = {
            "mean_spread": _finite_mean([item["mean_spread"] for item in rows]),
            "positive_spread_window_ratio": _positive_ratio([item["mean_spread"] for item in rows]),
            "mean_positive_spread_period_ratio": _finite_mean(
                [item["positive_spread_ratio"] for item in rows]
            ),
            "mean_selected_realized_percentile": _finite_mean(
                [item["mean_selected_realized_percentile"] for item in rows]
            ),
            "selected_above_median_window_ratio": _positive_ratio(
                [
                    (
                        None
                        if item["mean_selected_realized_percentile"] is None
                        else item["mean_selected_realized_percentile"] - 0.5
                    )
                    for item in rows
                ]
            ),
        }
    return {
        "n_windows": len(factor_windows),
        "mean_daily_rank_ic": _finite_mean([item["mean_rank_ic"] for item in daily]),
        "mean_daily_rank_icir": _finite_mean([item["rank_icir"] for item in daily]),
        "positive_daily_rank_ic_window_ratio": _positive_ratio(
            [item["mean_rank_ic"] for item in daily]
        ),
        "mean_daily_quintile_spread": _finite_mean(
            [item["quintile"]["mean_spread"] for item in daily]
        ),
        "positive_daily_quintile_spread_window_ratio": _positive_ratio(
            [item["quintile"]["mean_spread"] for item in daily]
        ),
        "rebalance_fixed_tails": fixed_tails,
    }


def _aggregate_diagnostics(
    window_reports: list[dict[str, Any]],
    *,
    source_aggregate: dict[str, Any],
) -> dict[str, Any]:
    if len(window_reports) != REQUIRED_WINDOWS:
        raise ValueError(f"requires exactly {REQUIRED_WINDOWS} diagnostic windows")

    factor_ids = [item["id"] for item in FROZEN_FACTOR_DEFINITIONS]
    factors: list[dict[str, Any]] = []
    for factor_id in factor_ids:
        factor_windows = [
            next(item for item in window["factors"] if item["factor"]["id"] == factor_id)
            for window in window_reports
        ]
        original = _orientation_aggregate(factor_windows, "original")
        inverted = _orientation_aggregate(factor_windows, "inverted")
        original_rank_ic = original["mean_daily_rank_ic"]
        preferred = (
            "inverted" if original_rank_ic is not None and original_rank_ic < 0.0 else "original"
        )
        preferred_metrics = original if preferred == "original" else inverted
        top3 = preferred_metrics["rebalance_fixed_tails"]["3"]
        checks = {
            "mean_daily_rank_ic": _greater(
                preferred_metrics["mean_daily_rank_ic"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_mean_daily_rank_ic"],
            ),
            "mean_daily_rank_icir": _greater(
                preferred_metrics["mean_daily_rank_icir"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_mean_daily_rank_icir"],
            ),
            "positive_daily_rank_ic_window_ratio": _at_least(
                preferred_metrics["positive_daily_rank_ic_window_ratio"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_positive_daily_rank_ic_window_ratio"],
            ),
            "mean_daily_quintile_spread": _greater(
                preferred_metrics["mean_daily_quintile_spread"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_mean_daily_quintile_spread"],
            ),
            "positive_daily_quintile_spread_window_ratio": _at_least(
                preferred_metrics["positive_daily_quintile_spread_window_ratio"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS[
                    "min_positive_daily_quintile_spread_window_ratio"
                ],
            ),
            "rebalance_top3_spread": _greater(
                top3["mean_spread"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_rebalance_top3_spread"],
            ),
            "positive_rebalance_top3_window_ratio": _at_least(
                top3["positive_spread_window_ratio"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_positive_rebalance_top3_window_ratio"],
            ),
            "positive_rebalance_top3_period_ratio": _at_least(
                top3["mean_positive_spread_period_ratio"],
                DIAGNOSTIC_CONSISTENCY_THRESHOLDS["min_positive_rebalance_top3_period_ratio"],
            ),
        }
        factor = factor_windows[0]["factor"]
        factors.append(
            {
                **factor,
                "orientations": {
                    "original": original,
                    "inverted": inverted,
                },
                "descriptive_preferred_orientation": preferred,
                "preferred_orientation_selected_on_same_oos_evidence": True,
                "preferred_orientation_metrics": preferred_metrics,
                "diagnostic_consistency_thresholds": dict(DIAGNOSTIC_CONSISTENCY_THRESHOLDS),
                "diagnostic_consistency_checks": checks,
                "failed_diagnostic_consistency_checks": [
                    name for name, passed in checks.items() if not passed
                ],
                "passes_diagnostic_consistency_checks": all(checks.values()),
                "promotion_eligible": False,
                "trade_ready": False,
            }
        )

    model_score = source_aggregate.get("score_diagnostics", {})
    model_tail = source_aggregate.get("selection_tail_diagnostics", {})
    broad_rank_ic_positive = bool(
        isinstance(model_score.get("mean_rank_ic_ir"), (int, float))
        and model_score["mean_rank_ic_ir"] > 0.0
    )
    top3_spread_positive = bool(
        isinstance(model_tail.get("mean_spread"), (int, float)) and model_tail["mean_spread"] > 0.0
    )
    selected_percentile = model_tail.get("mean_selected_realized_percentile")
    broad_ic_tail_disconnect = broad_rank_ic_positive and not top3_spread_positive

    ranked = sorted(
        factors,
        key=lambda item: (
            item["preferred_orientation_metrics"]["rebalance_fixed_tails"]["3"]["mean_spread"]
            if item["preferred_orientation_metrics"]["rebalance_fixed_tails"]["3"]["mean_spread"]
            is not None
            else float("-inf")
        ),
        reverse=True,
    )
    descriptive_highest_top3 = ranked[0] if ranked else None
    consistent_factor_ids = [
        item["id"] for item in factors if item["passes_diagnostic_consistency_checks"]
    ]
    resolution_windows: list[dict[str, Any]] = []
    for window in window_reports:
        n_symbols = int(window["n_oos_symbols"])
        expected_top_gain_bin_size = int(np.ceil(n_symbols / FROZEN_CALIBRATION.n_gain_bins))
        resolution_windows.append(
            {
                "window": window["window"]["label"],
                "n_oos_symbols": n_symbols,
                "expected_top_gain_bin_size": expected_top_gain_bin_size,
                "portfolio_top_k": FROZEN_TOP_N,
                "top_gain_bin_to_portfolio_ratio": (expected_top_gain_bin_size / FROZEN_TOP_N),
            }
        )
    minimum_top_gain_bin_size = min(
        item["expected_top_gain_bin_size"] for item in resolution_windows
    )
    gain_resolution_mismatch = minimum_top_gain_bin_size > FROZEN_TOP_N
    configured_ranker_params = FROZEN_CALIBRATION.params()
    effective_truncation_level = int(
        configured_ranker_params.get(
            "lambdarank_truncation_level",
            LIGHTGBM_DEFAULT_LAMBDARANK_TRUNCATION_LEVEL,
        )
    )
    topk_aligned_reference_level = FROZEN_TOP_N + 3
    truncation_level_mismatch = effective_truncation_level > topk_aligned_reference_level
    objective_topk_alignment_mismatch = gain_resolution_mismatch or truncation_level_mismatch

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "candidate_v2_ndx_cross_sectional_factor_diagnostics",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "n_windows": len(window_reports),
        "candidate_reference": {
            "candidate": source_aggregate.get("candidate"),
            "mean_rank_ic": model_score.get("mean_rank_ic"),
            "mean_rank_icir": model_score.get("mean_rank_ic_ir"),
            "mean_daily_quintile_spread": model_score.get("mean_top_bottom_spread"),
            "rebalance_top3_mean_spread": model_tail.get("mean_spread"),
            "rebalance_top3_positive_spread_ratio": model_tail.get("mean_positive_spread_ratio"),
            "mean_selected_realized_percentile": selected_percentile,
            "compounded_relative_excess_return": source_aggregate.get("candidate_v2", {}).get(
                "compounded_relative_excess_return"
            ),
            "worst_drawdown": source_aggregate.get("candidate_v2", {}).get("worst_drawdown"),
        },
        "target_resolution_diagnosis": {
            "training_target": "processed_daily_percentile_rank",
            "ranker_objective": "lambdarank",
            "n_gain_bins": FROZEN_CALIBRATION.n_gain_bins,
            "portfolio_top_k": FROZEN_TOP_N,
            "gain_resolution_mismatch": gain_resolution_mismatch,
            "effective_lambdarank_truncation_level": effective_truncation_level,
            "truncation_level_source": (
                "configured"
                if "lambdarank_truncation_level" in configured_ranker_params
                else "lightgbm_default"
            ),
            "topk_aligned_reference_level": topk_aligned_reference_level,
            "truncation_level_to_portfolio_topk_ratio": (effective_truncation_level / FROZEN_TOP_N),
            "truncation_level_mismatch": truncation_level_mismatch,
            "objective_topk_alignment_mismatch": (objective_topk_alignment_mismatch),
            "minimum_expected_top_gain_bin_size": minimum_top_gain_bin_size,
            "minimum_top_gain_bin_to_portfolio_ratio": (minimum_top_gain_bin_size / FROZEN_TOP_N),
            "per_window": resolution_windows,
            "interpretation": (
                "The highest gain label covers roughly the top 20% of each "
                "cross-section while the portfolio selects only Top-3. "
                "LambdaRank therefore receives no gain-label resolution "
                "inside most of the portfolio selection tail. The frozen "
                "model also inherits LightGBM's truncation level 30, so its "
                "ranking objective is much broader than portfolio Top-3."
            ),
            "not_a_parameter_recommendation": True,
        },
        "diagnosis": {
            "broad_rank_ic_positive": broad_rank_ic_positive,
            "rebalance_top3_spread_positive": top3_spread_positive,
            "selected_top3_above_random": bool(
                isinstance(selected_percentile, (int, float)) and selected_percentile > 0.5
            ),
            "broad_ic_tail_disconnect": broad_ic_tail_disconnect,
            "gain_resolution_mismatch": gain_resolution_mismatch,
            "truncation_level_mismatch": truncation_level_mismatch,
            "objective_topk_alignment_mismatch": (objective_topk_alignment_mismatch),
            "factors_passing_all_consistency_checks": consistent_factor_ids,
            "descriptive_highest_top3_spread_factor": (
                None
                if descriptive_highest_top3 is None
                else {
                    "id": descriptive_highest_top3["id"],
                    "orientation": descriptive_highest_top3["descriptive_preferred_orientation"],
                    "mean_top3_spread": descriptive_highest_top3["preferred_orientation_metrics"][
                        "rebalance_fixed_tails"
                    ]["3"]["mean_spread"],
                    "positive_top3_window_ratio": descriptive_highest_top3[
                        "preferred_orientation_metrics"
                    ]["rebalance_fixed_tails"]["3"]["positive_spread_window_ratio"],
                    "same_oos_selection_not_deployable": True,
                }
            ),
            "conclusion": (
                "broad_cross_section_signal_does_not_survive_top3_concentration"
                if broad_ic_tail_disconnect
                else "no_broad_ic_top3_disconnect_detected"
            ),
            "next_step": (
                "test one predeclared tail-aware target/objective hypothesis "
                "on untouched windows; do not grid-search gain bins, Top-K, "
                "or orientation on this evidence"
            ),
        },
        "factors": factors,
    }


def _window_model_reference(payload: dict[str, Any]) -> dict[str, Any]:
    tail = payload["selection_tail_diagnostics"]["aggregate"]
    score = payload["score_diagnostics"]
    return {
        "mean_rank_ic": score["rank_ic_mean"],
        "rank_icir": score["rank_ic_ir"],
        "daily_quintile_spread": score["top_bottom_spread_mean"],
        "rebalance_top3_mean_spread": tail["mean_spread"],
        "rebalance_top3_positive_spread_ratio": tail["positive_spread_ratio"],
        "mean_selected_realized_percentile": tail["mean_selected_realized_percentile"],
        "relative_excess_return": payload["candidate_v2"]["relative_excess_return"],
        "max_drawdown": payload["candidate_v2"]["max_drawdown"],
    }


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Generate fixed-factor diagnostics bound to existing NDX evidence."""

    root = root.resolve()
    effective_data_root = data_root.resolve() if data_root is not None else root
    source_dir = source_dir if source_dir.is_absolute() else root / source_dir
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    _validate_frozen_factor_contract()

    provider_manifest = _verify_us_provider(effective_data_root)
    provider_identity = str(provider_manifest["provider_identity_sha256"])
    source_manifest, source_aggregate, source_windows, source_hashes = _load_source_evidence(
        source_dir,
        provider_identity=provider_identity,
    )

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(effective_data_root, "us"))
    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market="us",
            provider_uri_default=provider_uri,
        )
    )
    from qlib.data import D

    per_window_dir = output_dir / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{payload['window']['label']}.json" for payload in source_windows}
    for stale_path in per_window_dir.glob("*.json"):
        if stale_path.name not in expected_names:
            stale_path.unlink()

    factor_expressions = [item["expression"] for item in FROZEN_FACTOR_DEFINITIONS]
    window_reports: list[dict[str, Any]] = []
    for source_window in sorted(
        source_windows,
        key=lambda payload: str(payload["window"]["label"]),
    ):
        window = source_window["window"]
        label = str(window["label"])
        symbols = list(source_window["coverage_meta"]["oos_test_symbols"])
        rebalance_dates = [
            item["date"] for item in source_window["selection_tail_diagnostics"]["periods"]
        ]
        if len(rebalance_dates) != len(set(rebalance_dates)):
            raise ValueError(f"{label} rebalance dates must be unique")

        frame = D.features(
            symbols,
            [*factor_expressions, CANONICAL_10D_RETURN_EXPR],
            start_time=window["test_start"],
            end_time=window["test_end"],
        )
        frame = _normalize_index(frame).replace([np.inf, -np.inf], np.nan)
        if frame.empty:
            raise ValueError(f"{label} provider returned no diagnostic data")
        if frame.shape[1] != len(factor_expressions) + 1:
            raise ValueError(f"{label} provider returned unexpected columns")

        feature_frame = frame.iloc[:, :-1].copy()
        feature_frame.columns = [item["id"] for item in FROZEN_FACTOR_DEFINITIONS]
        raw_returns = frame.iloc[:, [-1]].copy()
        raw_returns.columns = ["return"]
        raw_returns.attrs["provenance"] = "raw_forward_return"
        raw_returns.attrs["horizon"] = 10
        raw_returns.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

        factors: list[dict[str, Any]] = []
        for definition in FROZEN_FACTOR_DEFINITIONS:
            score = feature_frame.loc[:, [definition["id"]]].copy()
            score.columns = ["score"]
            diagnostic = diagnose_cross_sectional_score(
                score,
                raw_returns,
                rebalance_dates=rebalance_dates,
                tail_sizes=TAIL_SIZES,
            )
            factors.append(
                {
                    "factor": dict(definition),
                    "diagnostic": diagnostic,
                }
            )

        report = {
            "schema_version": SCHEMA_VERSION,
            "evidence_type": ("candidate_v2_ndx_cross_sectional_factor_diagnostics_window"),
            "research_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
            "window": window,
            "oos_snapshot_date": source_window["coverage_meta"]["oos_snapshot_date"],
            "n_oos_symbols": len(symbols),
            "oos_symbols": symbols,
            "n_rebalance_dates": len(rebalance_dates),
            "raw_return_provenance": {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": CANONICAL_10D_RETURN_EXPR,
            },
            "candidate_model_reference": _window_model_reference(source_window),
            "factors": factors,
        }
        _write_json(per_window_dir / f"{label}.json", report)
        window_reports.append(report)

        print(f"{label}: symbols={len(symbols)} rebalance_dates={len(rebalance_dates)}")

    aggregate = _aggregate_diagnostics(
        window_reports,
        source_aggregate=source_aggregate,
    )
    aggregate_path = output_dir / "aggregate.json"
    _write_json(aggregate_path, aggregate)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "candidate_v2_ndx_cross_sectional_factor_diagnostics",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "diagnostic_only": True,
        "new_model_trained": False,
        "parameter_search_performed": False,
        "orientation_selected_for_deployment": False,
        "source_candidate": source_manifest["candidate"],
        "source_evidence_dir": str(source_dir),
        "source_evidence_hashes": source_hashes,
        "provider_uri": provider_uri,
        "provider_identity_sha256": provider_identity,
        "n_windows": len(window_reports),
        "tail_sizes": list(TAIL_SIZES),
        "factor_definitions": [dict(item) for item in FROZEN_FACTOR_DEFINITIONS],
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
        "point_in_time_scope": {
            "oos_membership_point_in_time": True,
            "training_membership_asof_semiannual": True,
            "full_daily_point_in_time": False,
        },
        "aggregate_artifact": aggregate_path.name,
        "per_window_artifacts": [
            f"per_window/{report['window']['label']}.json" for report in window_reports
        ],
    }
    manifest_path = output_dir / "evidence_manifest.json"
    _write_json(manifest_path, manifest)

    diagnosis = aggregate["diagnosis"]
    print(f"aggregate: {aggregate_path}")
    print(f"manifest:  {manifest_path}")
    print(f"diagnosis: {diagnosis['conclusion']}")
    print(
        f"descriptive highest Top-3 spread: {diagnosis['descriptive_highest_top3_spread_factor']}"
    )
    print("promotion_eligible: false")
    print("trade_ready: false")

    return {
        "aggregate_path": str(aggregate_path),
        "manifest_path": str(manifest_path),
        "aggregate": aggregate,
        "manifest": manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Read-only data root containing data/providers/us",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Existing candidate_v2 NDX evidence directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Diagnostic evidence output directory",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        args.root,
        data_root=args.data_root,
        source_dir=args.source_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
