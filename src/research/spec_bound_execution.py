"""Spec-bound execution identity gate.

This module connects a validated research contract to an execution adapter without
allowing the adapter to reinterpret the declared universe, factors, candidates,
strategy, split, or evaluation semantics.

The adapter must return the effective contract it actually used. Evidence may be
attached only when the canonical declared and effective contracts are identical.
Promotion is finalized only after that identity proof succeeds.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.research.model_decision_pack import render_model_decision_markdown
from src.research.multi_market_readiness import load_market_watchlist
from src.research.paradigm import (
    ResearchParadigmSpec,
    build_factor_baselines_from_spec,
    build_ranker_candidates_from_spec,
    validate_research_paradigm_spec,
)
from src.research.promotion_consumers import (
    build_frontend_promotion_view,
    build_model_decision_pack_view,
)
from src.research.promotion_decision import (
    PromotionDecision,
    PromotionStatus,
    build_promotion_decision_from_run,
    write_promotion_decision,
)
from src.research.research_artifacts import (
    ResearchRunPaths,
    build_research_run_paths,
    write_json,
    write_run_status,
)

EXECUTION_CONTRACT_SCHEMA_VERSION = "1.1"
DECLARED_EXECUTION_CONTRACT_FILENAME = "declared_execution_contract.json"
EFFECTIVE_EXECUTION_CONTRACT_FILENAME = "effective_execution_contract.json"
EXECUTION_IDENTITY_FILENAME = "execution_identity.json"


@dataclass(frozen=True)
class SpecBoundExecutionPlan:
    """Immutable declared execution plan passed to an execution adapter."""

    spec: ResearchParadigmSpec
    candidates: tuple[dict[str, Any], ...]
    baseline_factors: dict[str, str]
    declared_contract: dict[str, Any]
    declared_contract_sha256: str


@dataclass(frozen=True)
class SpecBoundExecutionResult:
    """Execution adapter result before evidence is accepted by the core gate."""

    status: str
    effective_contract: dict[str, Any]
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    evidence_paths: dict[str, str] = field(default_factory=dict)


SpecBoundExecutor = Callable[
    [SpecBoundExecutionPlan, Path], SpecBoundExecutionResult
]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def contract_sha256(payload: dict[str, Any]) -> str:
    """Return the canonical SHA-256 identity for an execution contract."""

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _source_path(spec: ResearchParadigmSpec, source: str) -> Path:
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else Path.cwd()
    for candidate in (spec_dir / source, Path.cwd() / source):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Source '{source}' not found relative to spec dir ({spec_dir}) or cwd"
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_declared_execution_contract(
    spec: ResearchParadigmSpec,
) -> dict[str, Any]:
    """Build the complete contract that a runtime adapter must execute exactly."""

    validate_research_paradigm_spec(spec)

    universe_source = str(spec.universe["source"])
    universe_path = _source_path(spec, universe_source)
    requested_symbols = load_market_watchlist(
        spec.market,
        watchlist_path=universe_path,
    )
    min_symbols = int(spec.universe["min_symbols"])
    if len(requested_symbols) < min_symbols:
        raise ValueError(
            f"Declared universe contains {len(requested_symbols)} symbols, "
            f"below min_symbols={min_symbols}"
        )

    factor_source = str(spec.factor_library["source"])
    factor_path = _source_path(spec, factor_source)
    candidates = build_ranker_candidates_from_spec(spec)
    baseline_factors = build_factor_baselines_from_spec(spec)

    return {
        "schema_version": EXECUTION_CONTRACT_SCHEMA_VERSION,
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "benchmark": spec.benchmark,
        "universe": {
            "source": universe_source,
            "source_sha256": _file_sha256(universe_path),
            "market_key": str(spec.universe["market_key"]),
            "requested_symbols": requested_symbols,
            "min_symbols": min_symbols,
            "alignment_mode": str(spec.universe["alignment_mode"]),
        },
        "factors": {
            "source": factor_source,
            "source_sha256": _file_sha256(factor_path),
            "selected_groups": [
                str(name) for name in spec.factor_library["groups"]
            ],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "baseline_factors": dict(sorted(baseline_factors.items())),
        },
        "strategy": dict(spec.strategy),
        "walk_forward": dict(spec.walk_forward),
        "evaluation": dict(spec.evaluation),
        "outputs": dict(spec.outputs),
    }


def build_spec_bound_execution_plan(
    spec: ResearchParadigmSpec,
) -> SpecBoundExecutionPlan:
    """Build the immutable adapter input from one validated paradigm spec."""

    declared_contract = build_declared_execution_contract(spec)
    candidates = tuple(
        dict(item) for item in declared_contract["factors"]["candidates"]
    )
    baseline_factors = dict(declared_contract["factors"]["baseline_factors"])
    return SpecBoundExecutionPlan(
        spec=spec,
        candidates=candidates,
        baseline_factors=baseline_factors,
        declared_contract=declared_contract,
        declared_contract_sha256=contract_sha256(declared_contract),
    )


def _contract_differences(
    declared: Any,
    effective: Any,
    *,
    path: str = "$",
) -> list[str]:
    differences: list[str] = []
    if type(declared) is not type(effective):
        return [
            f"{path}: type {type(declared).__name__} != "
            f"{type(effective).__name__}"
        ]
    if isinstance(declared, dict):
        declared_keys = set(declared)
        effective_keys = set(effective)
        for key in sorted(declared_keys - effective_keys):
            differences.append(f"{path}.{key}: missing from effective contract")
        for key in sorted(effective_keys - declared_keys):
            differences.append(f"{path}.{key}: unexpected effective field")
        for key in sorted(declared_keys & effective_keys):
            differences.extend(
                _contract_differences(
                    declared[key], effective[key], path=f"{path}.{key}"
                )
            )
        return differences
    if isinstance(declared, list):
        if len(declared) != len(effective):
            differences.append(
                f"{path}: length {len(declared)} != {len(effective)}"
            )
        for index, (left, right) in enumerate(zip(declared, effective)):
            differences.extend(
                _contract_differences(left, right, path=f"{path}[{index}]")
            )
        return differences
    if declared != effective:
        differences.append(f"{path}: {declared!r} != {effective!r}")
    return differences


def assert_execution_contract_identity(
    declared: dict[str, Any],
    effective: dict[str, Any],
) -> None:
    """Fail closed unless declared and effective execution contracts are exact."""

    differences = _contract_differences(declared, effective)
    if differences:
        preview = "; ".join(differences[:10])
        if len(differences) > 10:
            preview += f"; ... {len(differences) - 10} more"
        raise ValueError(f"Spec-bound execution contract mismatch: {preview}")


def _resolve_evidence_paths(
    evidence_paths: dict[str, str],
    run_dir: Path,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, raw_path in evidence_paths.items():
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise FileNotFoundError(
                f"Execution adapter declared missing evidence file '{name}': {candidate}"
            )
        resolved[name] = str(candidate)
    return resolved


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _mark_test_only_evidence(
    paths: ResearchRunPaths,
    runtime_metadata: dict[str, Any],
) -> None:
    """Persist an auditable scope marker for generated CI providers."""

    provider_uri = str(runtime_metadata.get("provider_uri", "")).strip()
    if not provider_uri:
        return
    fixture_manifest = Path(provider_uri) / "fixture_manifest.json"
    if not fixture_manifest.is_file():
        return
    readiness = _read_optional_json(paths.data_readiness)
    if not readiness:
        return
    readiness.update(
        {
            "evidence_scope": "synthetic_ci",
            "test_only": True,
            "fixture_manifest": str(fixture_manifest.resolve()),
        }
    )
    write_json(paths.data_readiness, readiness)


def _build_scoped_promotion(
    spec: ResearchParadigmSpec,
    paths: ResearchRunPaths,
) -> dict[str, Any]:
    """Build one promotion result and reject explicitly test-only evidence."""

    decision = build_promotion_decision_from_run(
        paths.run_dir,
        subject_id=spec.experiment_id,
    )
    readiness = _read_optional_json(paths.data_readiness)
    if bool(readiness.get("test_only")) and not decision.missing_evidence:
        decision = PromotionDecision(
            subject_id=decision.subject_id,
            status=PromotionStatus.REJECTED,
            trade_ready=False,
            candidate=decision.candidate,
            failed_gates=("evidence_scope",),
            evidence_refs=decision.evidence_refs,
            contract_sha256=decision.contract_sha256,
            thresholds=decision.thresholds,
            rationale=(
                "Synthetic or test-only provider evidence may validate execution "
                "mechanics but cannot support research promotion."
            ),
        )
    promotion_path = write_promotion_decision(paths.run_dir, decision)
    payload = decision.to_dict()
    payload["artifact_path"] = str(promotion_path)
    return payload


def _finalize_promotion_outputs(
    spec: ResearchParadigmSpec,
    paths: ResearchRunPaths,
    *,
    run_status: str,
    resolved_evidence_paths: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Write every decision surface from one post-identity promotion result."""

    promotion = _build_scoped_promotion(spec, paths)
    promotion_path = Path(str(promotion["artifact_path"]))

    decision_pack = build_model_decision_pack_view(promotion)
    write_json(paths.model_decision_pack, decision_pack)
    paths.model_decision_markdown.write_text(
        render_model_decision_markdown(decision_pack),
        encoding="utf-8",
    )

    metrics = _read_optional_json(paths.metrics_summary)
    if metrics:
        metrics["current_best_candidate"] = promotion.get("candidate")
        metrics["decision"] = dict(decision_pack["decision"])
        metrics["decision_source"] = "promotion_decision"
        metrics["promotion_contract_sha256"] = str(
            promotion.get("contract_sha256", "")
        )
        write_json(paths.metrics_summary, metrics)

    readiness = _read_optional_json(paths.data_readiness)
    artifact_paths = {
        **resolved_evidence_paths,
        "execution_identity": str(
            paths.run_dir / EXECUTION_IDENTITY_FILENAME
        ),
        "promotion_decision": str(promotion_path),
        "model_decision_pack": str(paths.model_decision_pack),
        "model_decision_markdown": str(paths.model_decision_markdown),
    }
    if paths.metrics_summary.is_file():
        artifact_paths["metrics_summary"] = str(paths.metrics_summary)

    frontend = build_frontend_promotion_view(
        promotion,
        market=spec.market,
        benchmark=spec.benchmark,
        run_status=run_status,
        metrics=metrics,
        readiness=readiness,
        artifact_paths=artifact_paths,
    )
    write_json(paths.frontend_payload, frontend)
    artifact_paths["frontend_payload"] = str(paths.frontend_payload)
    return promotion, artifact_paths


def execute_spec_bound_research(
    spec: ResearchParadigmSpec,
    executor: SpecBoundExecutor,
    *,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Execute, prove identity, then finalize one canonical decision surface."""

    plan = build_spec_bound_execution_plan(spec)
    paths: ResearchRunPaths = build_research_run_paths(
        root,
        spec.experiment_id,
        output_dir=output_dir,
    )
    paths.ensure_dir()

    declared_path = paths.run_dir / DECLARED_EXECUTION_CONTRACT_FILENAME
    effective_path = paths.run_dir / EFFECTIVE_EXECUTION_CONTRACT_FILENAME
    identity_path = paths.run_dir / EXECUTION_IDENTITY_FILENAME
    write_json(declared_path, plan.declared_contract)

    result = executor(plan, paths.run_dir)
    if result.status not in {"passed", "skipped"}:
        raise ValueError(
            "Spec-bound executor status must be 'passed' or 'skipped'; "
            f"got {result.status!r}"
        )

    write_json(effective_path, result.effective_contract)
    declared_sha = plan.declared_contract_sha256
    effective_sha = contract_sha256(result.effective_contract)
    differences = _contract_differences(
        plan.declared_contract,
        result.effective_contract,
    )

    identity_payload = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "matched": not differences,
        "declared_contract_sha256": declared_sha,
        "effective_contract_sha256": effective_sha,
        "differences": differences,
    }
    write_json(identity_path, identity_payload)

    if differences:
        write_run_status(
            paths,
            experiment_id=spec.experiment_id,
            status="failed",
            failed_stage="execution_identity",
            reason="Declared and effective execution contracts differ",
            extra={
                "declared_contract_sha256": declared_sha,
                "effective_contract_sha256": effective_sha,
                "difference_count": len(differences),
            },
        )
        assert_execution_contract_identity(
            plan.declared_contract,
            result.effective_contract,
        )

    resolved_evidence_paths = _resolve_evidence_paths(
        result.evidence_paths,
        paths.run_dir,
    )
    _mark_test_only_evidence(paths, dict(result.runtime_metadata))
    promotion, finalized_paths = _finalize_promotion_outputs(
        spec,
        paths,
        run_status=result.status,
        resolved_evidence_paths=resolved_evidence_paths,
    )
    runtime_metadata = {
        **dict(result.runtime_metadata),
        "decision_source": "promotion_decision",
        "decision_status": str(promotion["status"]),
    }
    decision_view = {
        "status": str(promotion["status"]),
        "trade_ready": bool(promotion["trade_ready"]),
    }
    write_run_status(
        paths,
        experiment_id=spec.experiment_id,
        status=result.status,
        reason="Spec-bound execution contract identity verified",
        decision=decision_view,
        extra={
            "declared_contract_sha256": declared_sha,
            "effective_contract_sha256": effective_sha,
            "execution_identity": str(identity_path),
            "runtime_metadata": runtime_metadata,
            "evidence_paths": finalized_paths,
            "promotion_decision": promotion,
        },
    )

    return {
        "status": result.status,
        "run_dir": str(paths.run_dir),
        "contract_identity_verified": True,
        "declared_contract_sha256": declared_sha,
        "effective_contract_sha256": effective_sha,
        "runtime_metadata": runtime_metadata,
        "evidence_paths": finalized_paths,
        "promotion_decision": promotion,
    }
