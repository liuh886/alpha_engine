"""Development-only redundancy diagnostics for canonical ranker factor additions.

The diagnostic never loads a forward-return label. It evaluates added factors on
the exact OOS evaluation dates already declared as candidate-selection windows
and reports correlation against the frozen baseline feature set.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_execution import (
    candidate_factor_contracts,
    resolve_symbols,
    runtime_for_market,
)
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window

SCHEMA_VERSION = "1.0"


def _mean_daily_rank_corr(left: pd.Series, right: pd.Series) -> tuple[float, int]:
    frame = pd.concat([left.rename("left"), right.rename("right")], axis=1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    values: list[float] = []
    for _, group in frame.groupby(level="datetime"):
        if len(group) < 5:
            continue
        left_rank = group["left"].rank(method="average")
        right_rank = group["right"].rank(method="average")
        if left_rank.std(ddof=0) <= 1e-12 or right_rank.std(ddof=0) <= 1e-12:
            continue
        corr = left_rank.corr(right_rank)
        if np.isfinite(corr):
            values.append(float(corr))
    return (float(np.mean(values)) if values else 0.0, len(values))


def _global_pearson(left: pd.Series, right: pd.Series) -> float:
    frame = pd.concat([left.rename("left"), right.rename("right")], axis=1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 2 or frame["left"].std(ddof=0) <= 1e-12 or frame["right"].std(ddof=0) <= 1e-12:
        return 0.0
    value = frame["left"].corr(frame["right"])
    return float(value) if np.isfinite(value) else 0.0


def evaluate_factor_redundancy(
    spec_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    runtime = runtime_for_market(spec.market)
    runtime.initialize(PROJECT_ROOT)
    runtime_metadata = runtime.metadata()
    observed_provider = str(runtime_metadata.get("provider_identity_sha256") or "")
    if observed_provider != spec.contract.provider_identity_sha256:
        raise ValueError(
            "factor redundancy provider identity mismatch: "
            f"expected={spec.contract.provider_identity_sha256}, observed={observed_provider}"
        )

    symbols = resolve_symbols(spec, runtime)
    contracts = candidate_factor_contracts(spec)
    baseline_id = spec.contract.baseline_candidate_id
    baseline = contracts[baseline_id]
    baseline_pairs = list(zip(baseline["factor_ids"], baseline["expressions"], strict=True))
    baseline_ids = {str(value) for value in baseline["factor_ids"]}

    added_expression_by_id: dict[str, str] = {}
    candidate_added_ids: dict[str, list[str]] = {}
    for candidate in spec.candidates:
        contract = contracts[candidate.candidate_id]
        additions = [
            str(factor_id)
            for factor_id in contract["factor_ids"]
            if str(factor_id) not in baseline_ids
        ]
        candidate_added_ids[candidate.candidate_id] = additions
        for factor_id, expression in zip(contract["factor_ids"], contract["expressions"], strict=True):
            if str(factor_id) in additions:
                previous = added_expression_by_id.get(str(factor_id))
                if previous is not None and previous != str(expression):
                    raise ValueError(f"added factor expression drifted: {factor_id}")
                added_expression_by_id[str(factor_id)] = str(expression)

    if not added_expression_by_id:
        raise ValueError("redundancy diagnostic resolved no incremental factors")

    walk = spec.parent.walk_forward
    strategy = spec.parent.strategy
    calendar = runtime.calendar(
        str(walk["requested_train_start"]),
        min(str(walk["test_end"]), spec.contract.cutoff),
    )
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
        min_partial_window_eligible_sessions=walk.get("min_partial_window_eligible_sessions"),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    dates_by_window = horizon_eligible_dates_by_window(plan, calendar)
    selected_windows = [
        window for window in plan.selected_windows if window.label in spec.contract.selection_windows
    ]
    labels = [window.label for window in selected_windows]
    if labels != list(spec.contract.selection_windows):
        raise ValueError(
            f"redundancy selection windows drifted: expected={list(spec.contract.selection_windows)}, "
            f"observed={labels}"
        )

    expressions = list(
        dict.fromkeys(
            [expression for _, expression in baseline_pairs]
            + list(added_expression_by_id.values())
        )
    )
    expression_to_column = {expression: f"f{index}" for index, expression in enumerate(expressions)}
    frames: list[pd.DataFrame] = []
    for window in selected_windows:
        raw = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                expressions,
                window.test_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        raw.columns = [expression_to_column[expression] for expression in expressions]
        eligible_dates = dates_by_window[window.label]
        mask = raw.index.get_level_values("datetime").isin(eligible_dates)
        frames.append(raw.loc[mask].copy())
    frame = pd.concat(frames).sort_index()
    if frame.empty:
        raise ValueError("redundancy diagnostic feature frame is empty")

    factors: dict[str, Any] = {}
    for factor_id, added_expression in added_expression_by_id.items():
        added = frame[expression_to_column[added_expression]]
        pairs: list[dict[str, Any]] = []
        for baseline_factor_id, baseline_expression in baseline_pairs:
            base = frame[expression_to_column[baseline_expression]]
            rank_corr, n_dates = _mean_daily_rank_corr(added, base)
            pairs.append(
                {
                    "baseline_factor_id": baseline_factor_id,
                    "global_pearson": _global_pearson(added, base),
                    "mean_daily_rank_correlation": rank_corr,
                    "rank_correlation_date_count": n_dates,
                }
            )
        strongest = max(pairs, key=lambda row: abs(float(row["mean_daily_rank_correlation"])))
        factors[factor_id] = {
            "expression": added_expression,
            "row_count": int(added.notna().sum()),
            "max_abs_mean_daily_rank_correlation": abs(
                float(strongest["mean_daily_rank_correlation"])
            ),
            "strongest_baseline_factor_id": strongest["baseline_factor_id"],
            "pairs": pairs,
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "scope": "selection_window_features_only_no_forward_label",
        "provider_identity_sha256": observed_provider,
        "cutoff": spec.contract.cutoff,
        "selection_windows": list(spec.contract.selection_windows),
        "baseline_candidate_id": baseline_id,
        "baseline_factor_ids": list(baseline["factor_ids"]),
        "candidate_added_factor_ids": candidate_added_ids,
        "factors": factors,
        "feature_frame_sha256": hashlib.sha256(
            frame.to_csv(index=True, lineterminator="\n", float_format="%.17g").encode("utf-8")
        ).hexdigest(),
        "research_only": True,
        "trade_ready": False,
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
