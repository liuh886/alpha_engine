"""Bind one active research mission to an accepted formal baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.formal_baseline import load_formal_baseline

RUNNER_ID = "formal_baseline_onboarding_v1"


def _load_spec(path: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    resolved.relative_to(PROJECT_ROOT.resolve())
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("baseline onboarding spec must be a mapping")
    if raw.get("runner") != RUNNER_ID:
        raise ValueError(f"baseline onboarding runner must be {RUNNER_ID!r}")
    if raw.get("research_only") is not True or raw.get("trade_ready") is not False:
        raise ValueError("baseline onboarding must remain research_only=true, trade_ready=false")
    if raw.get("active") is not True:
        raise ValueError("baseline onboarding spec must be active")
    return resolved, raw


def run_formal_baseline_onboarding(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Bind one active mission to the exact accepted formal baseline declared by the spec."""

    resolved, raw = _load_spec(spec_path)
    baseline_raw = raw.get("baseline")
    if not isinstance(baseline_raw, dict):
        raise ValueError("baseline onboarding spec requires baseline mapping")

    baseline = load_formal_baseline(
        str(baseline_raw["model_version_id"]),
        expected_model_kind=str(baseline_raw["model_kind"]),
        expected_model_family_id=str(baseline_raw["model_family_id"]),
        expected_bundle_id=str(baseline_raw["bundle_id"]),
        expected_manifest_sha256=str(baseline_raw["manifest_sha256"]),
    )
    expected = raw.get("expected_identity") or {}
    if expected.get("market") and baseline.market != str(expected["market"]):
        raise ValueError("formal baseline market does not match onboarding spec")
    if expected.get("benchmark") and baseline.benchmark != str(expected["benchmark"]):
        raise ValueError("formal baseline benchmark does not match onboarding spec")
    if expected.get("evidence_cutoff") and baseline.evidence_cutoff != str(
        expected["evidence_cutoff"]
    ):
        raise ValueError("formal baseline evidence_cutoff does not match onboarding spec")

    receipt = {
        "schema_version": "1.0",
        "experiment_id": str(raw["experiment_id"]),
        "runner": RUNNER_ID,
        "status": "completed",
        "decision": "formal_baseline_bound",
        "baseline": baseline.to_receipt(),
        "source_spec": str(resolved.relative_to(PROJECT_ROOT)),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    target = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (
            PROJECT_ROOT / "artifacts" / "research_experiments" / str(raw["experiment_id"])
        ).resolve()
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / "research_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
