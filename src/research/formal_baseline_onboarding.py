"""Research-loop onboarding for immutable formal model baselines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.formal_baseline import load_formal_baseline

RUNNER_ID = "formal_baseline_onboarding_v1"
_COMPLETED_STATUS = "completed"
_BASELINE_IDENTITY_FIELDS = (
    "model_version_id",
    "model_family_id",
    "model_kind",
    "bundle_id",
    "manifest_sha256",
)


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
    return resolved, raw


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _completed_receipt_path(spec: dict[str, Any]) -> Path:
    raw_path = spec.get("result_receipt")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("completed baseline onboarding spec requires result_receipt")
    path = (PROJECT_ROOT / raw_path).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_completed_onboarding_record(spec_path: str | Path) -> dict[str, Any]:
    """Validate one completed onboarding record without consulting today's catalog.

    A completed research mission is historical evidence. Its pinned bundle/hash
    identity must remain stable even when the same accepted model version later
    receives a refreshed formal publication. This validator therefore checks the
    completed spec against its committed receipt only; it deliberately does not
    resolve the mutable current formal catalog.
    """

    _, spec = _load_spec(spec_path)
    if spec.get("active") is not False or spec.get("status") != _COMPLETED_STATUS:
        raise ValueError("historical onboarding validation requires an inactive completed spec")

    baseline_spec = spec.get("baseline")
    if not isinstance(baseline_spec, dict):
        raise ValueError("baseline onboarding spec requires baseline mapping")

    receipt = _load_json_object(_completed_receipt_path(spec))
    if receipt.get("runner") != RUNNER_ID:
        raise ValueError("completed onboarding receipt runner mismatch")
    if receipt.get("status") != _COMPLETED_STATUS:
        raise ValueError("completed onboarding receipt status mismatch")
    if receipt.get("decision") != "formal_baseline_bound":
        raise ValueError("completed onboarding receipt decision mismatch")
    if receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
        raise ValueError("completed onboarding receipt safety contract mismatch")
    if receipt.get("automatic_promotion") is not False:
        raise ValueError("completed onboarding receipt cannot authorize automatic promotion")
    if receipt.get("experiment_id") != spec.get("experiment_id"):
        raise ValueError("completed onboarding receipt experiment_id mismatch")

    baseline_receipt = receipt.get("baseline")
    if not isinstance(baseline_receipt, dict):
        raise ValueError("completed onboarding receipt requires baseline mapping")
    for field in _BASELINE_IDENTITY_FIELDS:
        if baseline_receipt.get(field) != baseline_spec.get(field):
            raise ValueError(f"completed onboarding baseline {field} mismatch")

    expected = spec.get("expected_identity") or {}
    if not isinstance(expected, dict):
        raise ValueError("baseline onboarding expected_identity must be a mapping")
    for field in ("market", "benchmark", "evidence_cutoff"):
        expected_value = expected.get(field)
        if expected_value is not None and baseline_receipt.get(field) != expected_value:
            raise ValueError(f"completed onboarding baseline {field} mismatch")

    return receipt


def run_formal_baseline_onboarding(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Bind a new active mission to the current accepted formal baseline.

    Completed/inactive onboarding specs are immutable historical records and may
    not be replayed against a later formal catalog. Use
    :func:`load_completed_onboarding_record` to validate those records instead.
    """

    resolved, raw = _load_spec(spec_path)
    if raw.get("active") is not True or raw.get("status") == _COMPLETED_STATUS:
        raise ValueError("completed or inactive baseline onboarding specs cannot be replayed")

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
        "status": _COMPLETED_STATUS,
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
            PROJECT_ROOT
            / "artifacts"
            / "research_experiments"
            / str(raw["experiment_id"])
        ).resolve()
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / "research_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
