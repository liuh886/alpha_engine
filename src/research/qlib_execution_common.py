"""Market-neutral helpers shared by spec-bound Qlib execution adapters.

This module owns only execution mechanics that are identical across markets.
Provider initialization, symbol normalization, readiness policy, and market
metadata remain in the CN and US adapters.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerFeatureGroup,
    RankerGridCandidate,
)
from src.research.research_artifacts import ResearchRunPaths, write_json
from src.research.spec_bound_execution import (
    SpecBoundExecutionPlan,
    SpecBoundExecutionResult,
)


def resolve_repository_root(plan: SpecBoundExecutionPlan) -> Path:
    """Resolve the repository root from a plan's source spec when possible."""

    spec_path = Path(plan.spec.spec_path).resolve() if plan.spec.spec_path else None
    if spec_path is not None:
        for parent in spec_path.parents:
            if (parent / "configs").is_dir() and (parent / "src").is_dir():
                return parent
    return Path.cwd()


def normalize_qlib_frame_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the canonical ``(datetime, instrument)`` sorted index layout."""

    if frame.index.names == ["instrument", "datetime"]:
        return frame.swaplevel().sort_index()
    return frame.sort_index()


def materialize_ranker_candidates(
    plan: SpecBoundExecutionPlan,
) -> tuple[RankerGridCandidate, ...]:
    """Reconstruct typed candidates without changing declared identities."""

    candidates: list[RankerGridCandidate] = []
    for raw in plan.candidates:
        feature_raw = dict(raw["feature_group"])
        calibration_raw = dict(raw["calibration"])
        candidate = RankerGridCandidate(
            feature_group=RankerFeatureGroup(
                name=str(feature_raw["name"]),
                expressions=tuple(
                    str(item) for item in feature_raw["expressions"]
                ),
            ),
            calibration=RankerCalibration(
                n_gain_bins=int(calibration_raw["n_gain_bins"]),
                num_boost_round=int(calibration_raw["num_boost_round"]),
                num_leaves=int(calibration_raw["num_leaves"]),
                min_data_in_leaf=int(calibration_raw["min_data_in_leaf"]),
                learning_rate=float(calibration_raw.get("learning_rate", 0.05)),
            ),
        )
        if candidate.name != str(raw["name"]):
            raise ValueError(
                "Candidate identity changed while materializing execution plan: "
                f"{raw['name']!r} != {candidate.name!r}"
            )
        candidates.append(candidate)
    return tuple(candidates)


def build_effective_execution_contract(
    plan: SpecBoundExecutionPlan,
    *,
    candidates: Sequence[RankerGridCandidate],
    baselines: dict[str, str],
    requested_symbols: Sequence[str],
) -> dict[str, Any]:
    """Rebuild the contract from the exact values consumed by an adapter."""

    declared = plan.declared_contract
    return {
        "schema_version": declared["schema_version"],
        "experiment_id": plan.spec.experiment_id,
        "market": plan.spec.market,
        "benchmark": plan.spec.benchmark,
        "universe": {
            "source": declared["universe"]["source"],
            "source_sha256": declared["universe"]["source_sha256"],
            "market_key": plan.spec.universe["market_key"],
            "requested_symbols": list(requested_symbols),
            "min_symbols": int(plan.spec.universe["min_symbols"]),
            "alignment_mode": str(plan.spec.universe["alignment_mode"]),
        },
        "factors": {
            "source": declared["factors"]["source"],
            "source_sha256": declared["factors"]["source_sha256"],
            "selected_groups": [
                str(item) for item in plan.spec.factor_library["groups"]
            ],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "baseline_factors": dict(sorted(baselines.items())),
        },
        "strategy": dict(plan.spec.strategy),
        "walk_forward": dict(plan.spec.walk_forward),
        "evaluation": dict(plan.spec.evaluation),
        "outputs": dict(plan.spec.outputs),
    }


def fit_ranker_scores(
    candidate: RankerGridCandidate,
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test: pd.DataFrame,
    expression_columns: dict[str, str],
) -> pd.DataFrame:
    """Fit one declared ranker and return test-period scores."""

    columns = [
        expression_columns[item]
        for item in candidate.feature_group.expressions
    ]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, columns],
        returns_train,
    )
    ranker = fit_lgbm_daily_ranker(
        x_rank,
        y_rank,
        groups,
        n_gain_bins=candidate.calibration.n_gain_bins,
        params=candidate.calibration.params(),
        num_boost_round=candidate.calibration.num_boost_round,
    )
    return predict_lgbm_daily_ranker(
        ranker,
        features_test.loc[:, columns],
    )


def build_skip_result(
    plan: SpecBoundExecutionPlan,
    *,
    paths: ResearchRunPaths,
    effective_contract: dict[str, Any],
    reason: str,
    runtime_metadata: dict[str, Any],
    evidence_paths: dict[str, str],
) -> SpecBoundExecutionResult:
    """Write one auditable skipped-execution artifact and result."""

    skip_path = paths.run_dir / "execution_skipped.json"
    write_json(
        skip_path,
        {
            "schema_version": "1.0",
            "experiment_id": plan.spec.experiment_id,
            "status": "skipped",
            "reason": reason,
            "research_only": True,
            "trade_ready": False,
            "runtime_metadata": runtime_metadata,
        },
    )
    return SpecBoundExecutionResult(
        status="skipped",
        effective_contract=effective_contract,
        runtime_metadata={**runtime_metadata, "skip_reason": reason},
        evidence_paths={
            **evidence_paths,
            "execution_skipped": str(skip_path),
        },
    )
