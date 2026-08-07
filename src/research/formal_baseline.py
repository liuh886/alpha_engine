"""Immutable formal-baseline identity for Alpha Research Loop missions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT

FORMAL_ROOT = PROJECT_ROOT / "data" / "research" / "formal_model_runs"
CATALOG_PATH = FORMAL_ROOT / "catalog.json"


@dataclass(frozen=True)
class FormalBaseline:
    model_version_id: str
    model_family_id: str
    model_kind: str
    run_id: str
    bundle_id: str
    evidence_cutoff: str
    manifest_path: Path
    manifest_sha256: str
    market: str
    benchmark: str
    metrics: dict[str, float | None]

    def to_receipt(self) -> dict[str, Any]:
        return {
            "model_version_id": self.model_version_id,
            "model_family_id": self.model_family_id,
            "model_kind": self.model_kind,
            "run_id": self.run_id,
            "bundle_id": self.bundle_id,
            "evidence_cutoff": self.evidence_cutoff,
            "manifest_path": str(self.manifest_path.relative_to(PROJECT_ROOT)),
            "manifest_sha256": self.manifest_sha256,
            "market": self.market,
            "benchmark": self.benchmark,
            "metrics": self.metrics,
        }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metric_map(summary: dict[str, Any]) -> dict[str, float | None]:
    rows = summary.get("metrics")
    if not isinstance(rows, list):
        raise ValueError("formal summary.metrics must be a list")
    metrics: dict[str, float | None] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric_id = str(row.get("metric_id", "")).strip()
        if not metric_id:
            continue
        value = row.get("value")
        metrics[metric_id] = None if value is None else float(value)
    return metrics


def _catalog_record(model_version_id: str) -> dict[str, Any]:
    catalog = _load_json(CATALOG_PATH)
    if catalog.get("schema_version") != "2.0.0" or catalog.get("channel") != "formal":
        raise ValueError("formal model-run catalog contract is invalid")
    records = catalog.get("records")
    if not isinstance(records, list):
        raise ValueError("formal model-run catalog records must be a list")
    matches = [
        dict(row)
        for row in records
        if isinstance(row, dict) and row.get("model_version_id") == model_version_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one formal baseline for {model_version_id!r}, found {len(matches)}"
        )
    return matches[0]


def load_formal_baseline(
    model_version_id: str,
    *,
    expected_model_kind: str | None = None,
    expected_model_family_id: str | None = None,
    expected_bundle_id: str | None = None,
    expected_manifest_sha256: str | None = None,
) -> FormalBaseline:
    """Load and hash-verify one accepted formal baseline bundle."""

    record = _catalog_record(model_version_id)
    if record.get("publication_status") != "accepted_formal_baseline":
        raise ValueError(f"{model_version_id} is not an accepted formal baseline")

    manifest_path = (FORMAL_ROOT / str(record["manifest_path"])).resolve()
    manifest_path.relative_to(FORMAL_ROOT.resolve())
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest_sha = _sha256(manifest_path)
    if manifest_sha != str(record["manifest_sha256"]):
        raise ValueError(f"catalog manifest hash mismatch for {model_version_id}")

    manifest = _load_json(manifest_path)
    expected_pairs = {
        "model_version_id": record["model_version_id"],
        "model_family_id": record["model_family_id"],
        "model_kind": record["model_kind"],
        "run_id": record["run_id"],
        "bundle_id": record["bundle_id"],
        "evidence_cutoff": record["evidence_cutoff"],
        "publication_status": "accepted_formal_baseline",
        "publication_channel": "formal",
    }
    for field, expected in expected_pairs.items():
        if manifest.get(field) != expected:
            raise ValueError(
                f"formal manifest {field} mismatch: expected={expected!r} "
                f"observed={manifest.get(field)!r}"
            )

    if expected_model_kind is not None and manifest["model_kind"] != expected_model_kind:
        raise ValueError("formal baseline model_kind does not match mission")
    if (
        expected_model_family_id is not None
        and manifest["model_family_id"] != expected_model_family_id
    ):
        raise ValueError("formal baseline model_family_id does not match mission")
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ValueError("formal baseline bundle_id does not match mission")
    if expected_manifest_sha256 is not None and manifest_sha != expected_manifest_sha256:
        raise ValueError("formal baseline manifest_sha256 does not match mission")

    sections = manifest.get("sections")
    if not isinstance(sections, list):
        raise ValueError("formal manifest sections must be a list")
    bundle_dir = manifest_path.parent
    summary_path: Path | None = None
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("formal manifest section must be an object")
        required = bool(section.get("required_for_model_kind"))
        available = section.get("availability_status") == "available"
        if required and not available:
            raise ValueError(
                f"required formal section unavailable: {section.get('section_id')}"
            )
        if not available:
            continue
        relative = str(section.get("path", ""))
        path = (bundle_dir / relative).resolve()
        path.relative_to(bundle_dir.resolve())
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(section["byte_size"]):
            raise ValueError(f"formal section byte_size mismatch: {relative}")
        if _sha256(path) != str(section["sha256"]):
            raise ValueError(f"formal section sha256 mismatch: {relative}")
        if section.get("section_id") == "summary":
            summary_path = path

    if summary_path is None:
        raise ValueError("formal baseline has no retained summary section")
    summary = _load_json(summary_path)
    if summary.get("model_version_id") != model_version_id:
        raise ValueError("formal summary model_version_id mismatch")
    comparability = manifest.get("comparability_key") or {}
    market = str(summary.get("market") or comparability.get("market") or "")
    benchmark = str(summary.get("benchmark") or comparability.get("benchmark_id") or "")
    if not market or not benchmark:
        raise ValueError("formal baseline market/benchmark identity is incomplete")

    return FormalBaseline(
        model_version_id=model_version_id,
        model_family_id=str(manifest["model_family_id"]),
        model_kind=str(manifest["model_kind"]),
        run_id=str(manifest["run_id"]),
        bundle_id=str(manifest["bundle_id"]),
        evidence_cutoff=str(manifest["evidence_cutoff"]),
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        market=market,
        benchmark=benchmark,
        metrics=_metric_map(summary),
    )
