from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.data.model_data_bundle import (
    ModelDataBundleError,
    verify_model_data_bundle,
)


def _load_manifest(bundle_root: Path) -> dict[str, Any]:
    path = bundle_root / "model-data-bundle.json"
    if not path.is_file():
        raise ModelDataBundleError(f"model-data-bundle.json is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ModelDataBundleError("model-data-bundle.json must be a mapping")
    return payload


def check_profile(
    bundle_root: str | Path,
    profile_id: str,
    *,
    expected_pool_id: str | None = None,
    maximum_evidence_cutoff: str | None = None,
) -> dict[str, Any]:
    """Return one verified ready profile or raise a fail-closed error."""

    root = Path(bundle_root).resolve()
    verified_indexes = verify_model_data_bundle(root)
    manifest = _load_manifest(root)
    profiles = manifest.get("training_profiles", [])
    matches = [
        row
        for row in profiles
        if isinstance(row, dict) and str(row.get("profile_id")) == profile_id
    ]
    if len(matches) != 1:
        raise ModelDataBundleError(f"training profile must resolve exactly once: {profile_id}")
    profile = matches[0]
    if profile.get("status") != "ready":
        failed = profile.get("failed_gates", [])
        raise ModelDataBundleError(
            f"training profile is blocked: {profile_id}; failed_gates={failed}"
        )
    if profile.get("trade_ready") is not False:
        raise ModelDataBundleError(
            f"training profile has invalid trade_ready boundary: {profile_id}"
        )
    if expected_pool_id is not None:
        observed_pool = str(profile.get("candidate_pool_id", ""))
        if observed_pool != expected_pool_id:
            raise ModelDataBundleError(
                "training profile pool mismatch: "
                f"expected={expected_pool_id}, observed={observed_pool}"
            )
    if maximum_evidence_cutoff is not None:
        observed_cutoff = str(manifest.get("evidence_cutoff", ""))
        if not observed_cutoff or observed_cutoff > maximum_evidence_cutoff:
            raise ModelDataBundleError(
                "model data cutoff exceeds training contract: "
                f"maximum={maximum_evidence_cutoff}, "
                f"observed={observed_cutoff or 'missing'}"
            )
    return {
        "profile_id": profile_id,
        "status": "ready",
        "bundle_id": manifest.get("bundle_id"),
        "evidence_cutoff": manifest.get("evidence_cutoff"),
        "candidate_pool_id": profile.get("candidate_pool_id"),
        "candidate_count": profile.get("candidate_count"),
        "references": profile.get("references", []),
        "verified_indexes": verified_indexes,
        "research_only": True,
        "trade_ready": False,
    }
