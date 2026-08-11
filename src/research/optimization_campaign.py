"""Compile agent-proposed model deltas into one fixed-context experiment.

Campaign owners freeze data, factors, windows, costs, baseline and candidate
search space. Agents submit only bounded candidate deltas. The compiler rejects
context drift and materializes all accepted challengers into one experiment so
the existing runner can share provider reads and union feature loading.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.data.model_data_bundle import verify_model_data_bundle

CAMPAIGN_SCHEMA_VERSION = "1.0"
RUNNER_ID = "cross_sectional_xgb_ranker_v1"
_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_FILES = (
    "src/research/cross_sectional_experiment_runner.py",
    "src/research/experiment_harness.py",
    "src/research/xgb_native_calibration.py",
    "src/research/optimization_campaign.py",
    "uv.lock",
)


class OptimizationCampaignError(ValueError):
    """Raised when a campaign or submission changes frozen research context."""


@dataclass(frozen=True)
class CompiledOptimizationCampaign:
    campaign_id: str
    context_sha256: str
    model_data_bundle_id: str
    compiled_spec_path: Path
    manifest_path: Path
    candidate_trial_ids: Mapping[str, str]


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OptimizationCampaignError(f"invalid YAML mapping: {path}") from exc
    if not isinstance(payload, dict):
        raise OptimizationCampaignError(f"expected YAML mapping: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_repo_path(root: Path, raw: Any, *, require_file: bool = False) -> Path:
    path = Path(str(raw))
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OptimizationCampaignError(f"path escapes repository root: {raw}") from exc
    if require_file and not resolved.is_file():
        raise OptimizationCampaignError(f"required campaign file is missing: {raw}")
    return resolved


def _require_boundary(payload: Mapping[str, Any], label: str) -> None:
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise OptimizationCampaignError(
            f"{label} must declare research_only=true and trade_ready=false"
        )


def _verify_frozen_files(
    campaign: Mapping[str, Any],
    *,
    root: Path,
    base_spec: Mapping[str, Any],
) -> dict[str, str]:
    rows = campaign.get("immutable_files")
    if not isinstance(rows, list) or not rows:
        raise OptimizationCampaignError("immutable_files must be a non-empty list")
    verified: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OptimizationCampaignError("immutable file records must be mappings")
        raw_path = str(row.get("path", ""))
        expected = str(row.get("sha256", "")).lower()
        if not _SHA256.fullmatch(expected):
            raise OptimizationCampaignError(f"invalid immutable file hash: {raw_path}")
        path = _resolve_repo_path(root, raw_path, require_file=True)
        observed = _sha256(path)
        if observed != expected:
            raise OptimizationCampaignError(
                f"immutable file drift: {raw_path}; expected {expected}, got {observed}"
            )
        verified[path.relative_to(root).as_posix()] = observed

    required_sources = {
        str((base_spec.get("factor_library") or {}).get("source", "")),
        str((base_spec.get("fixed_model") or {}).get("frozen_spec", "")),
    }
    missing = sorted(
        source
        for source in required_sources
        if source and _resolve_repo_path(root, source).relative_to(root).as_posix() not in verified
    )
    if missing:
        raise OptimizationCampaignError(
            f"factor library and frozen model must be immutable_files: {missing}"
        )
    return dict(sorted(verified.items()))


def _runtime_identity(root: Path) -> dict[str, str]:
    """Bind optimizer receipts to the exact runner and dependency implementation."""

    return {
        raw: _sha256(_resolve_repo_path(root, raw, require_file=True))
        for raw in RUNTIME_FILES
    }


def _verify_model_data(
    campaign: Mapping[str, Any],
    *,
    root: Path,
    expected_provider_identity: str,
) -> tuple[Path, dict[str, Any], list[str]]:
    contract = campaign.get("model_data_bundle")
    if not isinstance(contract, dict):
        raise OptimizationCampaignError("model_data_bundle must be a mapping")
    bundle_root = _resolve_repo_path(root, contract.get("root", ""))
    try:
        verify_model_data_bundle(bundle_root)
    except ValueError as exc:
        raise OptimizationCampaignError(f"model data bundle verification failed: {exc}") from exc
    readiness = json.loads(
        (bundle_root / "model-data-readiness.json").read_text(encoding="utf-8")
    )
    profiles = json.loads((bundle_root / "training-profiles.json").read_text(encoding="utf-8"))
    expected_bundle_id = str(contract.get("bundle_id", ""))
    if readiness.get("bundle_id") != expected_bundle_id:
        raise OptimizationCampaignError(
            "model data bundle identity drift: "
            f"expected {expected_bundle_id}, got {readiness.get('bundle_id')}"
        )
    required = [str(value) for value in contract.get("required_ready_profiles", [])]
    if not required:
        raise OptimizationCampaignError("required_ready_profiles must not be empty")
    statuses = {
        str(row.get("profile_id")): str(row.get("status"))
        for row in profiles
        if isinstance(row, dict)
    }
    blocked = [profile_id for profile_id in required if statuses.get(profile_id) != "ready"]
    if blocked:
        raise OptimizationCampaignError(f"model data training profiles are blocked: {blocked}")
    required_rows = [
        row
        for row in profiles
        if isinstance(row, dict) and str(row.get("profile_id")) in required
    ]
    price_requirements = [
        requirement
        for row in required_rows
        for requirement in row.get("required_components", [])
        if isinstance(requirement, dict)
        and (requirement.get("observed") or {}).get("component_kind")
        == "selected_pool_prices"
    ]
    price_provider_ids = {
        str(((row.get("observed") or {}).get("details") or {}).get(
            "provider_identity_sha256", ""
        ))
        for row in price_requirements
    }
    if "" in price_provider_ids:
        raise OptimizationCampaignError(
            "selected-pool model data is missing provider identity"
        )
    if price_provider_ids and price_provider_ids != {expected_provider_identity}:
        raise OptimizationCampaignError(
            "model data provider identity does not match the frozen experiment: "
            f"{sorted(price_provider_ids)} != {expected_provider_identity}"
        )
    return bundle_root, readiness, required


def _candidate_rows(base_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = base_spec.get("candidates")
    if not isinstance(rows, list):
        raise OptimizationCampaignError("base experiment candidates must be a list")
    candidates = [copy.deepcopy(row) for row in rows if isinstance(row, dict)]
    if len(candidates) != len(rows):
        raise OptimizationCampaignError("base experiment candidate entries must be mappings")
    return candidates


def _allowed_value(value: Any, allowed: Any) -> bool:
    return isinstance(allowed, list) and any(value == item for item in allowed)


def _materialize_candidates(
    campaign: Mapping[str, Any],
    submissions: Mapping[str, Any],
    *,
    base_spec: Mapping[str, Any],
    context_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if submissions.get("campaign_id") != campaign.get("campaign_id"):
        raise OptimizationCampaignError("submission campaign_id does not match campaign")
    _require_boundary(submissions, "candidate submissions")
    rows = submissions.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise OptimizationCampaignError("submissions require at least one candidate")
    maximum = int(campaign.get("max_challengers", 0))
    if maximum < 1 or len(rows) > maximum:
        raise OptimizationCampaignError(
            f"submitted {len(rows)} challengers; campaign maximum is {maximum}"
        )

    base_candidates = _candidate_rows(base_spec)
    baseline_id = str(campaign.get("baseline_candidate_id", ""))
    template_id = str(campaign.get("candidate_template_id", ""))
    matches = {str(row.get("candidate_id")): row for row in base_candidates}
    if baseline_id not in matches or matches[baseline_id].get("role") != "baseline":
        raise OptimizationCampaignError("frozen baseline candidate is missing or not baseline")
    if template_id not in matches or matches[template_id].get("role") != "challenger":
        raise OptimizationCampaignError("candidate template is missing or not challenger")
    search_space = campaign.get("search_space")
    if not isinstance(search_space, dict):
        raise OptimizationCampaignError("search_space must be a mapping")
    factor_space = search_space.get("factor_groups")
    xgb_space = search_space.get("xgb_native")
    if not isinstance(factor_space, list) or not isinstance(xgb_space, dict):
        raise OptimizationCampaignError(
            "search_space requires factor_groups list and xgb_native mapping"
        )
    if "seed" in xgb_space:
        raise OptimizationCampaignError("model seed is frozen and cannot be a search axis")

    result = [copy.deepcopy(matches[baseline_id])]
    trial_ids: dict[str, str] = {}
    baseline = matches[baseline_id]
    materialized_hashes = {
        _canonical_sha256(
            {
                "factor_groups": baseline.get("factor_groups"),
                "xgb_native": baseline.get("xgb_native"),
            }
        )
    }
    seen_ids = {baseline_id}
    for row in rows:
        if not isinstance(row, dict):
            raise OptimizationCampaignError("candidate submissions must be mappings")
        unexpected = sorted(set(row) - {"candidate_id", "factor_groups", "xgb_native"})
        if unexpected:
            raise OptimizationCampaignError(f"candidate contains forbidden fields: {unexpected}")
        candidate_id = str(row.get("candidate_id", ""))
        if not _CANDIDATE_ID.fullmatch(candidate_id) or candidate_id in seen_ids:
            raise OptimizationCampaignError(f"invalid or duplicate candidate_id: {candidate_id!r}")
        seen_ids.add(candidate_id)
        candidate = copy.deepcopy(matches[template_id])
        candidate["candidate_id"] = candidate_id
        candidate["role"] = "challenger"

        if "factor_groups" in row:
            factor_groups = row["factor_groups"]
            if not _allowed_value(factor_groups, factor_space):
                raise OptimizationCampaignError(
                    f"candidate {candidate_id} factor_groups are outside the search space"
                )
            candidate["factor_groups"] = copy.deepcopy(factor_groups)

        xgb_delta = row.get("xgb_native", {})
        if not isinstance(xgb_delta, dict):
            raise OptimizationCampaignError(f"candidate {candidate_id} xgb_native must be a mapping")
        forbidden_xgb = sorted(set(xgb_delta) - set(xgb_space))
        if forbidden_xgb:
            raise OptimizationCampaignError(
                f"candidate {candidate_id} changes forbidden xgb fields: {forbidden_xgb}"
            )
        xgb_native = copy.deepcopy(candidate.get("xgb_native") or {})
        for key, value in xgb_delta.items():
            if not _allowed_value(value, xgb_space[key]):
                raise OptimizationCampaignError(
                    f"candidate {candidate_id} value for {key} is outside the search space"
                )
            xgb_native[key] = value
        candidate["xgb_native"] = xgb_native
        materialized = {
            "factor_groups": candidate.get("factor_groups"),
            "xgb_native": candidate.get("xgb_native"),
        }
        materialized_sha = _canonical_sha256(materialized)
        if materialized_sha in materialized_hashes:
            raise OptimizationCampaignError("duplicate materialized candidates waste computation")
        materialized_hashes.add(materialized_sha)
        trial_ids[candidate_id] = _canonical_sha256(
            {"context_sha256": context_sha256, "candidate": materialized}
        )
        result.append(candidate)
    return result, trial_ids


def compile_optimization_campaign(
    campaign_path: str | Path,
    submissions_path: str | Path,
    output_dir: str | Path,
    *,
    repository_root: str | Path = PROJECT_ROOT,
) -> CompiledOptimizationCampaign:
    root = Path(repository_root).resolve()
    campaign_file = _resolve_repo_path(root, campaign_path, require_file=True)
    submissions_file = _resolve_repo_path(root, submissions_path, require_file=True)
    campaign = _load_mapping(campaign_file)
    submissions = _load_mapping(submissions_file)
    if str(campaign.get("schema_version")) != CAMPAIGN_SCHEMA_VERSION:
        raise OptimizationCampaignError("unsupported optimization campaign schema")
    _require_boundary(campaign, "optimization campaign")
    campaign_id = str(campaign.get("campaign_id", ""))
    if not _CANDIDATE_ID.fullmatch(campaign_id):
        raise OptimizationCampaignError(f"invalid campaign_id: {campaign_id!r}")

    base_contract = campaign.get("base_experiment")
    if not isinstance(base_contract, dict):
        raise OptimizationCampaignError("base_experiment must be a mapping")
    base_path = _resolve_repo_path(root, base_contract.get("path", ""), require_file=True)
    expected_base_sha = str(base_contract.get("sha256", "")).lower()
    if _sha256(base_path) != expected_base_sha:
        raise OptimizationCampaignError("base experiment hash drift")
    base_spec = _load_mapping(base_path)
    _require_boundary(base_spec, "base experiment")
    if base_spec.get("runner") != RUNNER_ID:
        raise OptimizationCampaignError(f"base experiment runner must be {RUNNER_ID}")
    snapshot = base_spec.get("snapshot") or {}
    expected_provider_identity = str(snapshot.get("provider_identity_sha256", ""))
    if not _SHA256.fullmatch(expected_provider_identity):
        raise OptimizationCampaignError("base experiment provider identity must be a sha256")
    immutable_files = _verify_frozen_files(campaign, root=root, base_spec=base_spec)
    bundle_root, readiness, required_profiles = _verify_model_data(
        campaign,
        root=root,
        expected_provider_identity=expected_provider_identity,
    )
    context = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "base_experiment": {
            "path": base_path.relative_to(root).as_posix(),
            "sha256": expected_base_sha,
        },
        "immutable_files": immutable_files,
        "runtime_files": _runtime_identity(root),
        "model_data_bundle": {
            "root": bundle_root.relative_to(root).as_posix(),
            "bundle_id": readiness["bundle_id"],
            "evidence_cutoff": readiness.get("evidence_cutoff"),
            "required_ready_profiles": required_profiles,
        },
        "provider_identity_sha256": snapshot.get("provider_identity_sha256"),
        "provider_cutoff": snapshot.get("cutoff"),
        "windows": base_spec.get("windows"),
        "execution": base_spec.get("execution"),
        "evaluation": base_spec.get("evaluation"),
        "runner": RUNNER_ID,
    }
    context_sha256 = _canonical_sha256(context)
    candidates, trial_ids = _materialize_candidates(
        campaign,
        submissions,
        base_spec=base_spec,
        context_sha256=context_sha256,
    )

    compiled = copy.deepcopy(base_spec)
    compiled["experiment_id"] = f"{campaign_id}__{context_sha256[:12]}"
    compiled["active"] = False
    compiled["status"] = "pre_registered_optimization_campaign"
    compiled["candidates"] = candidates
    compiled["optimization_campaign"] = {
        "campaign_id": campaign_id,
        "context_sha256": context_sha256,
        "model_data_bundle_id": readiness["bundle_id"],
        "shared_execution": "single_experiment_union_feature_load",
        "candidate_trial_ids": trial_ids,
        "automatic_promotion": False,
    }

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiled_path = output / "compiled-experiment.yaml"
    compiled_path.write_text(
        yaml.safe_dump(compiled, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "context_sha256": context_sha256,
        "context": context,
        "compiled_spec": compiled_path.name,
        "compiled_spec_sha256": _sha256(compiled_path),
        "candidate_trial_ids": trial_ids,
        "candidate_count": len(trial_ids),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    manifest_path = output / "campaign-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return CompiledOptimizationCampaign(
        campaign_id=campaign_id,
        context_sha256=context_sha256,
        model_data_bundle_id=str(readiness["bundle_id"]),
        compiled_spec_path=compiled_path,
        manifest_path=manifest_path,
        candidate_trial_ids=trial_ids,
    )


def verify_compiled_optimization_campaign(
    manifest_path: str | Path,
    *,
    repository_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizationCampaignError(f"invalid campaign manifest: {path}") from exc
    if not isinstance(manifest, dict):
        raise OptimizationCampaignError("campaign manifest must be a mapping")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise OptimizationCampaignError("compiled campaign has an invalid research boundary")
    compiled_path = path.parent / str(manifest.get("compiled_spec", ""))
    if not compiled_path.is_file() or _sha256(compiled_path) != manifest.get(
        "compiled_spec_sha256"
    ):
        raise OptimizationCampaignError("compiled experiment hash mismatch")
    context = manifest.get("context")
    if not isinstance(context, dict) or _canonical_sha256(context) != manifest.get(
        "context_sha256"
    ):
        raise OptimizationCampaignError("compiled campaign context hash mismatch")
    root = Path(repository_root).resolve()
    base = context.get("base_experiment") or {}
    base_path = _resolve_repo_path(root, base.get("path", ""), require_file=True)
    if _sha256(base_path) != base.get("sha256"):
        raise OptimizationCampaignError("compiled campaign base experiment drift")
    immutable_files = context.get("immutable_files") or {}
    if not isinstance(immutable_files, dict):
        raise OptimizationCampaignError("compiled immutable_files must be a mapping")
    for raw_path, expected in immutable_files.items():
        frozen_path = _resolve_repo_path(root, raw_path, require_file=True)
        if _sha256(frozen_path) != expected:
            raise OptimizationCampaignError(f"compiled immutable file drift: {raw_path}")
    runtime_files = context.get("runtime_files") or {}
    if runtime_files != _runtime_identity(root):
        raise OptimizationCampaignError("compiled optimizer runtime identity drift")
    bundle = context.get("model_data_bundle") or {}
    bundle_root = _resolve_repo_path(root, bundle.get("root", ""))
    verify_model_data_bundle(bundle_root)
    readiness = json.loads(
        (bundle_root / "model-data-readiness.json").read_text(encoding="utf-8")
    )
    if readiness.get("bundle_id") != bundle.get("bundle_id"):
        raise OptimizationCampaignError("compiled model data bundle drift")
    profiles = json.loads(
        (bundle_root / "training-profiles.json").read_text(encoding="utf-8")
    )
    required_profiles = set(bundle.get("required_ready_profiles", []))
    price_provider_ids = {
        str(((requirement.get("observed") or {}).get("details") or {}).get(
            "provider_identity_sha256", ""
        ))
        for row in profiles
        if isinstance(row, dict) and row.get("profile_id") in required_profiles
        for requirement in row.get("required_components", [])
        if isinstance(requirement, dict)
        and (requirement.get("observed") or {}).get("component_kind")
        == "selected_pool_prices"
    }
    if "" in price_provider_ids or (
        price_provider_ids
        and price_provider_ids != {str(context.get("provider_identity_sha256", ""))}
    ):
        raise OptimizationCampaignError("compiled model data provider identity drift")
    return manifest
