"""Validated fixed-10D research contract and Qlib-free preparation workflow.

This module deliberately stops at contract validation and artifact preparation.
It does not dispatch model training or reuse a runner whose effective inputs
cannot be proven identical to the declared paradigm spec.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.research.factor_library import (
    FactorGroup,
    factor_groups_to_ranker_feature_groups,
    factor_library_manifest,
    load_factor_library,
    resolve_factor_expressions,
    select_factor_groups,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerGridCandidate,
    build_ranker_calibration_grid,
)
from src.research.research_artifacts import (
    build_frontend_payload,
    build_research_run_paths,
    validate_artifact_completeness,
    write_frontend_payload,
    write_json,
    write_run_status,
    write_top_bottom_signals_csv,
)
from src.research.ten_day_model_gates import GATE_THRESHOLDS
from src.research.window_policy import (
    COMPLETE_WINDOWS_ONLY,
    validate_partial_window_contract,
)

PARADIGM_SCHEMA_VERSION = "1.1"
GATE_PROFILE = "ten_day_model_gates_v1"
ARTIFACT_PROFILE = "research_run_v1"
REQUIRED_METRICS: tuple[str, ...] = (
    "mean_icir",
    "mean_rank_ic",
    "mean_spread",
    "worst_drawdown",
    "ready_ratio",
    "positive_icir_ratio",
    "positive_spread_ratio",
)
_SAFE_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ResearchParadigmSpec:
    """One validated, serializable fixed-10D research contract."""

    schema_version: str
    experiment_id: str
    market: str
    benchmark: str
    universe: dict[str, Any]
    factor_library: dict[str, Any]
    candidate_grid: dict[str, Any]
    strategy: dict[str, Any]
    walk_forward: dict[str, Any]
    evaluation: dict[str, Any]
    outputs: dict[str, Any]
    spec_path: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ResearchParadigmSpec":
        yaml_path = Path(path).resolve()
        if not yaml_path.is_file():
            raise FileNotFoundError(f"Research paradigm spec not found: {yaml_path}")
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Research paradigm YAML must be a mapping")
        spec = cls.from_dict(data, spec_path=str(yaml_path))
        validate_research_paradigm_spec(spec)
        return spec

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], spec_path: str = ""
    ) -> "ResearchParadigmSpec":
        return cls(
            schema_version=str(data.get("schema_version", "")),
            experiment_id=str(data.get("experiment_id", "")),
            market=str(data.get("market", "")),
            benchmark=str(data.get("benchmark", "")),
            universe=dict(data.get("universe", {})),
            factor_library=dict(data.get("factor_library", {})),
            candidate_grid=dict(data.get("candidate_grid", {})),
            strategy=dict(data.get("strategy", {})),
            walk_forward=dict(data.get("walk_forward", {})),
            evaluation=dict(data.get("evaluation", {})),
            outputs=dict(data.get("outputs", {})),
            spec_path=spec_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "market": self.market,
            "benchmark": self.benchmark,
            "universe": dict(self.universe),
            "factor_library": dict(self.factor_library),
            "candidate_grid": dict(self.candidate_grid),
            "strategy": dict(self.strategy),
            "walk_forward": dict(self.walk_forward),
            "evaluation": dict(self.evaluation),
            "outputs": dict(self.outputs),
        }


def _resolve_relative_path(spec: ResearchParadigmSpec, source: str) -> Path:
    """Resolve a source from the spec directory or repository working directory."""
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else Path.cwd()
    candidates = (spec_dir / source, Path.cwd() / source)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Source '{source}' not found relative to spec dir ({spec_dir}) or cwd"
    )


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _require_non_empty_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    return value


def _parse_iso_date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


def _validate_calibrations(calibrations: list[Any]) -> None:
    required = (
        "n_gain_bins",
        "num_boost_round",
        "num_leaves",
        "min_data_in_leaf",
    )
    seen: set[tuple[int, int, int, int, float]] = set()
    for index, raw in enumerate(calibrations):
        item = _require_mapping(raw, f"candidate_grid.ranker.calibrations[{index}]")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(
                f"candidate_grid.ranker.calibrations[{index}] missing {missing}"
            )
        values = (
            int(item["n_gain_bins"]),
            int(item["num_boost_round"]),
            int(item["num_leaves"]),
            int(item["min_data_in_leaf"]),
            float(item.get("learning_rate", 0.05)),
        )
        if any(value <= 0 for value in values):
            raise ValueError("ranker calibration values must be positive")
        if values in seen:
            raise ValueError("ranker calibrations must be unique")
        seen.add(values)


def validate_research_paradigm_spec(spec: ResearchParadigmSpec) -> None:
    """Validate the complete fixed-10D preparation contract, failing closed."""
    if spec.schema_version != PARADIGM_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported paradigm schema_version '{spec.schema_version}' "
            f"(expected '{PARADIGM_SCHEMA_VERSION}')"
        )
    if not _SAFE_EXPERIMENT_ID.fullmatch(spec.experiment_id):
        raise ValueError(
            "experiment_id must be a safe slug containing only letters, numbers, "
            "dot, underscore, and hyphen"
        )
    if spec.market not in {"cn", "us"}:
        raise ValueError("market must be 'cn' or 'us'")
    if not spec.benchmark.strip():
        raise ValueError("benchmark must be non-empty")

    universe = _require_mapping(spec.universe, "universe")
    source = str(universe.get("source", ""))
    if not source:
        raise ValueError("universe.source must be non-empty")
    _resolve_relative_path(spec, source)
    if str(universe.get("market_key", "")) != spec.market:
        raise ValueError("universe.market_key must match top-level market")
    if int(universe.get("min_symbols", 0)) < 2:
        raise ValueError("universe.min_symbols must be >= 2")
    if str(universe.get("alignment_mode", "")) not in {"strict", "auto"}:
        raise ValueError("universe.alignment_mode must be 'strict' or 'auto'")

    factor_library = _require_mapping(spec.factor_library, "factor_library")
    factor_source = str(factor_library.get("source", ""))
    if not factor_source:
        raise ValueError("factor_library.source must be non-empty")
    _resolve_relative_path(spec, factor_source)
    groups = [str(item) for item in _require_non_empty_list(
        factor_library.get("groups"), "factor_library.groups"
    )]
    if len(groups) != len(set(groups)):
        raise ValueError("factor_library.groups must be unique")

    candidate_grid = _require_mapping(spec.candidate_grid, "candidate_grid")
    ranker = _require_mapping(candidate_grid.get("ranker"), "candidate_grid.ranker")
    calibrations = _require_non_empty_list(
        ranker.get("calibrations"),
        "candidate_grid.ranker.calibrations",
    )
    _validate_calibrations(calibrations)
    baselines = candidate_grid.get("factor_baselines", [])
    if not isinstance(baselines, list):
        raise ValueError("candidate_grid.factor_baselines must be a list")
    baseline_ids = [str(item) for item in baselines]
    if len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("candidate_grid.factor_baselines must be unique")

    strategy = _require_mapping(spec.strategy, "strategy")
    for field in ("horizon_days", "holding_days", "rebalance_days"):
        if int(strategy.get(field, 0)) != 10:
            raise ValueError(f"strategy.{field} must be 10")
    for field in ("top_n", "bottom_n"):
        if int(strategy.get(field, 0)) <= 0:
            raise ValueError(f"strategy.{field} must be positive")
    if str(strategy.get("return_expression", "")) != CANONICAL_10D_RETURN_EXPR:
        raise ValueError("strategy.return_expression must be the canonical 10D expression")
    if str(strategy.get("return_provenance", "")) != "raw_forward_return":
        raise ValueError("strategy.return_provenance must be 'raw_forward_return'")
    if strategy.get("research_only") is not True:
        raise ValueError("strategy.research_only must be True")

    walk_forward = _require_mapping(spec.walk_forward, "walk_forward")
    requested_start = _parse_iso_date(
        walk_forward.get("requested_train_start"),
        "walk_forward.requested_train_start",
    )
    test_end = _parse_iso_date(walk_forward.get("test_end"), "walk_forward.test_end")
    if requested_start >= test_end:
        raise ValueError("walk_forward.requested_train_start must be before test_end")
    first_year = int(walk_forward.get("first_test_year", 0))
    last_year = int(walk_forward.get("last_test_year", 0))
    if first_year > last_year:
        raise ValueError("walk_forward.first_test_year must be <= last_test_year")
    if int(walk_forward.get("min_windows", 0)) < 3:
        raise ValueError("walk_forward.min_windows must be >= 3")
    if int(walk_forward.get("train_embargo_sessions", 0)) != 10:
        raise ValueError("walk_forward.train_embargo_sessions must be 10")
    partial_policy = str(walk_forward.get("partial_window_policy", ""))
    raw_partial_minimum = walk_forward.get(
        "min_partial_window_eligible_sessions"
    )
    partial_minimum = (
        None if raw_partial_minimum is None else int(raw_partial_minimum)
    )
    validate_partial_window_contract(
        policy=partial_policy,
        min_partial_window_eligible_sessions=partial_minimum,
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    if partial_policy == COMPLETE_WINDOWS_ONLY and (
        "min_partial_window_eligible_sessions" in walk_forward
    ):
        raise ValueError(
            "complete_windows_only must not declare a partial-window session minimum"
        )

    evaluation = _require_mapping(spec.evaluation, "evaluation")
    if str(evaluation.get("benchmark_mode", "")) != "reference_only":
        raise ValueError("evaluation.benchmark_mode must be 'reference_only'")
    metrics = [
        str(item)
        for item in _require_non_empty_list(
            evaluation.get("metrics"), "evaluation.metrics"
        )
    ]
    if tuple(metrics) != REQUIRED_METRICS:
        raise ValueError(
            "evaluation.metrics must exactly match the canonical ordered metric set"
        )
    if str(evaluation.get("gate_profile", "")) != GATE_PROFILE:
        raise ValueError(f"evaluation.gate_profile must be '{GATE_PROFILE}'")
    if "gates" in evaluation:
        raise ValueError(
            "evaluation.gates must not duplicate thresholds; use gate_profile"
        )

    outputs = _require_mapping(spec.outputs, "outputs")
    if str(outputs.get("artifact_profile", "")) != ARTIFACT_PROFILE:
        raise ValueError(f"outputs.artifact_profile must be '{ARTIFACT_PROFILE}'")
    if set(outputs) != {"artifact_profile"}:
        raise ValueError("outputs may only contain artifact_profile")


def load_research_paradigm_spec(path: str | Path) -> ResearchParadigmSpec:
    """Load and validate a paradigm spec for notebooks or scripts."""
    return ResearchParadigmSpec.from_yaml(path)


def _parse_calibrations(
    candidate_grid: dict[str, Any],
) -> tuple[RankerCalibration, ...]:
    raw_items = candidate_grid["ranker"]["calibrations"]
    return tuple(
        RankerCalibration(
            n_gain_bins=int(item["n_gain_bins"]),
            num_boost_round=int(item["num_boost_round"]),
            num_leaves=int(item["num_leaves"]),
            min_data_in_leaf=int(item["min_data_in_leaf"]),
            learning_rate=float(item.get("learning_rate", 0.05)),
        )
        for item in raw_items
    )


def _selected_factor_groups(
    spec: ResearchParadigmSpec,
) -> tuple[Path, dict[str, FactorGroup], list[FactorGroup]]:
    library_path = _resolve_relative_path(spec, str(spec.factor_library["source"]))
    library = load_factor_library(library_path)
    selected = select_factor_groups(
        library, [str(name) for name in spec.factor_library["groups"]]
    )
    return library_path, library, selected


def build_ranker_candidates_from_spec(
    spec: ResearchParadigmSpec,
) -> list[RankerGridCandidate]:
    """Build the declared candidate grid without loading market data."""
    validate_research_paradigm_spec(spec)
    _, _, selected = _selected_factor_groups(spec)
    return build_ranker_calibration_grid(
        feature_groups=factor_groups_to_ranker_feature_groups(selected),
        calibrations=list(_parse_calibrations(spec.candidate_grid)),
    )


def build_factor_baselines_from_spec(
    spec: ResearchParadigmSpec,
) -> dict[str, str]:
    """Resolve every declared baseline id, failing closed if one is unknown."""
    validate_research_paradigm_spec(spec)
    _, library, _ = _selected_factor_groups(spec)
    baseline_ids = [str(item) for item in spec.candidate_grid["factor_baselines"]]
    expressions = resolve_factor_expressions(baseline_ids, library)
    return dict(zip(baseline_ids, expressions, strict=True))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dry_run_paradigm(
    spec: ResearchParadigmSpec,
    *,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and materialize the research contract without Qlib or training."""
    validate_research_paradigm_spec(spec)
    paths = build_research_run_paths(root, spec.experiment_id, output_dir=output_dir)
    paths.ensure_dir()

    library_path, library, selected_groups = _selected_factor_groups(spec)
    baselines = build_factor_baselines_from_spec(spec)
    candidates = build_ranker_candidates_from_spec(spec)
    calibrations = _parse_calibrations(spec.candidate_grid)

    factor_manifest = factor_library_manifest(selected_groups)
    factor_manifest.update(
        {
            "source": str(library_path),
            "source_sha256": _sha256(library_path),
            "selected_group_names": [group.name for group in selected_groups],
            "baseline_factors": baselines,
            "n_library_groups": len(library),
        }
    )
    candidate_manifest = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "n_candidates": len(candidates),
        "n_feature_groups": len(selected_groups),
        "n_calibrations": len(calibrations),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "gate_profile": GATE_PROFILE,
        "resolved_gate_thresholds": dict(GATE_THRESHOLDS),
    }

    write_json(paths.experiment_spec, spec.to_dict())
    write_json(paths.factor_manifest, factor_manifest)
    write_json(paths.candidate_manifest, candidate_manifest)
    write_json(paths.signals_latest, {"schema_version": "1.0", "signals": []})
    write_top_bottom_signals_csv(
        paths,
        [],
        market=spec.market,
        experiment_id=spec.experiment_id,
        holding_horizon_days=10,
    )
    write_run_status(
        paths,
        experiment_id=spec.experiment_id,
        status="prepared",
        reason="Contract validated; no Qlib initialization or model execution performed",
        extra={
            "artifact_profile": ARTIFACT_PROFILE,
            "gate_profile": GATE_PROFILE,
            "n_candidates": len(candidates),
        },
    )

    artifact_paths = paths.artifact_paths(existing_only=True)
    artifact_paths["frontend_payload"] = str(paths.frontend_payload)
    frontend = build_frontend_payload(
        spec.experiment_id,
        market=spec.market,
        benchmark=spec.benchmark,
        run_status="prepared",
        metrics={},
        gates=dict(GATE_THRESHOLDS),
        readiness={},
        artifact_paths=artifact_paths,
        metadata={
            "contract_only": True,
            "dry_run": True,
            "n_feature_factors": int(factor_manifest["n_factors"]),
            "n_candidates": len(candidates),
            "n_baseline_factors": len(baselines),
            "group_names": [group.name for group in selected_groups],
        },
    )
    write_frontend_payload(paths, frontend)
    validate_artifact_completeness(paths, profile=ARTIFACT_PROFILE)

    return {
        "status": "prepared",
        "run_dir": str(paths.run_dir),
        "n_feature_factors": int(factor_manifest["n_factors"]),
        "n_candidates": len(candidates),
        "n_baseline_factors": len(baselines),
        "group_names": [group.name for group in selected_groups],
        "contract_only": True,
    }


def run_research_paradigm(
    spec: ResearchParadigmSpec,
    root: str | Path | None = None,
    *,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Notebook-friendly contract preparation entry point.

    Real model execution is intentionally not supported in this PR. A later
    spec-bound runner must prove that declared and effective inputs are identical.
    """
    if dry_run is not True:
        raise ValueError(
            "Only dry_run=True is supported; spec-bound model execution is not implemented"
        )
    return dry_run_paradigm(spec, root=root, output_dir=output_dir)
