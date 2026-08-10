"""Create and validate manifest-bound research decision receipts.

Decision receipts are companion artifacts. They bind an immutable evidence
bundle by ``bundle_id`` and reference only section paths and SHA-256 values
already declared in that bundle's manifest. Keeping decisions outside the
manifest avoids a circular identity dependency.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    canonical_json_bytes,
    sha256_bytes,
    validate_decision,
    validate_manifest,
)

PROHIBITED_ACTION_LANGUAGE = re.compile(
    r"\b(buy|sell|place an order|position sizing|live trad(?:e|ing)|execute a trade)\b",
    re.IGNORECASE,
)


class ModelRunDecisionError(ModelRunBundleV2Error):
    """Decision receipt is not safely bound to its evidence bundle."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRunDecisionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ModelRunDecisionError(f"JSON root must be an object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelRunDecisionError(message)


def _claim_rows(decision: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for group in ("gates", "supporting_evidence", "contradictory_evidence"):
        value = decision.get(group)
        _require(isinstance(value, list), f"decision {group} missing")
        for row in value:
            _require(isinstance(row, Mapping), f"invalid decision claim in {group}")
            rows.append(row)
    return rows


def validate_bound_decision(manifest: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    """Validate decision semantics and every evidence reference."""

    validate_manifest(manifest)
    validate_decision(decision, manifest=manifest)
    sections = manifest.get("sections")
    assert isinstance(sections, list)
    available = {
        str(section["path"]): str(section["sha256"])
        for section in sections
        if isinstance(section, Mapping) and section.get("availability_status") == "available"
    }
    rows = _claim_rows(decision)
    _require(bool(decision.get("gates")), "at least one decision gate is required")
    claim_ids = [str(row.get("claim_id") or "") for row in rows]
    _require(len(claim_ids) == len(set(claim_ids)), "decision claim IDs must be unique")
    for row in rows:
        path = str(row.get("source_path") or "")
        digest = str(row.get("source_sha256") or "")
        _require(path in available, f"claim source is not an available manifest section: {path}")
        _require(available[path] == digest, f"claim source hash mismatch: {path}")

    gates = decision["gates"]
    assert isinstance(gates, list)
    outcomes = [str(row["outcome"]) for row in gates if isinstance(row, Mapping)]
    verdict = str(decision["verdict"])
    status = str(decision["status"])
    if status == "pending_review":
        _require(verdict == "blocked", "pending decision must remain blocked")
    if verdict == "supported":
        _require(status == "completed", "supported decision must be completed")
        _require(
            all(value == "passed" for value in outcomes),
            "supported decision requires all gates passed",
        )
        _require(
            not any(str(row.get("outcome")) in {"failed", "blocked"} for row in rows),
            "supported decision cannot retain failed or blocked evidence",
        )
    elif verdict == "not_supported":
        _require(status == "completed", "not_supported decision must be completed")
        _require("failed" in outcomes, "not_supported decision requires a failed gate")
    else:
        _require("blocked" in outcomes, "blocked decision requires a blocked gate")

    texts = [str(row.get("statement") or "") for row in rows]
    texts.extend(str(value) for value in decision.get("interpretation_limits", []))
    texts.extend(str(value) for value in decision.get("failure_modes", []))
    texts.append(str(decision.get("next_permitted_validation_step") or ""))
    _require(
        not any(PROHIBITED_ACTION_LANGUAGE.search(text) for text in texts),
        "decision contains prohibited trading-action language",
    )


def build_decision(*, manifest_path: Path, draft_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = _read(manifest_path)
    decision = _read(draft_path)
    validate_bound_decision(manifest, decision)
    encoded = canonical_json_bytes(decision)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    return {
        "schema_version": "2.0.0",
        "run_id": decision["run_id"],
        "bundle_id": decision["bundle_id"],
        "status": decision["status"],
        "verdict": decision["verdict"],
        "path": output_path.name,
        "sha256": sha256_bytes(encoded),
        "byte_size": len(encoded),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = build_decision(
        manifest_path=args.manifest,
        draft_path=args.draft,
        output_path=args.output,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
