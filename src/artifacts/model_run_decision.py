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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    canonical_json_bytes,
    sha256_bytes,
    validate_decision,
    validate_manifest,
    validate_catalog,
    compute_bundle_id,
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
        assert isinstance(value, list)
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


def pending_observation_decision(manifest_path: Path) -> dict[str, Any]:
    """Expose retained evidence without inventing a continuing-effectiveness gate."""
    manifest = _read(manifest_path)
    validate_manifest(manifest)
    _require(compute_bundle_id(manifest) == manifest["bundle_id"], "manifest bundle identity mismatch")
    sections: dict[str, tuple[Mapping[str, Any], dict[str, Any]]] = {}
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            continue
        path = manifest_path.parent / section["path"]
        encoded = path.read_bytes()
        _require(sha256_bytes(encoded) == section["sha256"], f"section hash mismatch: {path}")
        _require(len(encoded) == section["byte_size"], f"section byte size mismatch: {path}")
        payload = json.loads(encoded)
        if section["section_id"] in {"summary", "lineage", "robustness"}:
            _require(isinstance(payload, dict), "decision evidence section must be an object")
            sections[section["section_id"]] = (section, payload)

    def claim(identifier: str, outcome: str, statement: str, source: str) -> dict[str, Any]:
        section, _ = sections[source]
        return {
            "claim_id": identifier, "outcome": outcome, "statement": statement,
            "source_path": section["path"], "source_sha256": section["sha256"],
        }

    summary = sections["summary"][1]
    gates = [claim(
        "continuing-effectiveness-review", "blocked",
        "No completed continuing-effectiveness review is bound to this bundle. Historical baseline acceptance alone does not establish continued effectiveness.",
        "summary",
    )]
    contradictory = []
    limits = [
        "This pending receipt inventories retained evidence; it does not introduce performance thresholds or reopen model selection.",
        "Current observations have their own dates and identities; this historical bundle does not establish today's data freshness.",
    ]
    if "lineage" in sections:
        lineage = sections["lineage"][1]
        source = lineage.get("source_evidence", {})
        if isinstance(source, Mapping) and source.get("preregistered_gates_supported") is False:
            failed_gate = str(source.get("failed_gate") or "retained preregistered gate")
            gates.append(claim("retained-preregistered-rejection", "failed",
                f"The original preregistered evidence was not supported: {failed_gate}. Explicit user promotion does not turn this rejection into a passed gate.", "lineage"))
        for value in (lineage.get("known_limitations"), source.get("known_limitations") if isinstance(source, Mapping) else None):
            if isinstance(value, list):
                limits.extend(str(item) for item in value)
    if "robustness" in sections:
        robustness = sections["robustness"][1]
        if robustness.get("interpretation_limit"):
            limits.append(str(robustness["interpretation_limit"]))
        for row in robustness.get("window_summary", []):
            if not isinstance(row, Mapping):
                continue
            window = str(row.get("window") or "unknown")
            if row.get("preregistered_drawdown_gate_passed") is False:
                contradictory.append(claim(f"drawdown-gate-{window.lower()}", "failed",
                    f"{window}: retained preregistered drawdown gate failed; max drawdown {row.get('max_drawdown')}, incumbent {row.get('incumbent_max_drawdown')}.", "robustness"))
            if row.get("role") == "prospective_partial" or "PARTIAL" in window:
                relative = row.get("relative_excess_return", row.get("relative_excess"))
                contradictory.append(claim(f"partial-window-{window.lower().replace('_', '-')}", "informational",
                    f"{window}: incomplete observation; net return {row.get('total_return')}, relative excess {relative}, max drawdown {row.get('max_drawdown')}. This is not independent completed validation.", "robustness"))
    decision = {
        "schema_version": "2.0.0", "run_id": manifest["run_id"], "bundle_id": manifest["bundle_id"],
        "verdict": "blocked", "status": "pending_review", "gates": gates,
        "supporting_evidence": [claim("formal-baseline-identity", "informational",
            f"Retained baseline status: {summary.get('baseline_status', manifest['publication_status'])}; evidence cutoff {manifest['evidence_cutoff']}. Acceptance and validation are distinct.", "summary")],
        "contradictory_evidence": contradictory,
        "interpretation_limits": list(dict.fromkeys(limits)),
        "failure_modes": ["Short, selected or overlapping samples may overstate effectiveness; preserve failures and incomplete windows."],
        "next_permitted_validation_step": "Review retained failures and limitations, then bind a predeclared continuing-observation contract and sufficient prospective evidence to a reviewed companion receipt. Keep pool, factors, costs and parameters frozen.",
        "research_only": True, "trade_ready": False,
    }
    validate_bound_decision(manifest, decision)
    return decision


def materialize_pending_observation_decisions(*, catalog_path: Path, output_root: Path) -> dict[str, Any]:
    """Add missing companion receipts, preserving all existing reviewed decisions."""
    catalog = _read(catalog_path)
    validate_catalog(catalog)
    _require(catalog.get("channel") == "formal", "observation receipts require a formal catalog")
    index_path = output_root / "catalog.json"
    index = _read(index_path) if index_path.exists() else {
        "schema_version": "2.0.0", "records": [], "research_only": True, "trade_ready": False,
    }
    records = {row["bundle_id"]: row for row in index["records"]}
    for row in catalog["records"]:
        manifest_path = catalog_path.parent / row["manifest_path"]
        _require(sha256_bytes(manifest_path.read_bytes()) == row["manifest_sha256"], "catalog manifest hash mismatch")
        if row["bundle_id"] in records:
            existing = records[row["bundle_id"]]
            receipt_path = output_root / existing["path"]
            _require(sha256_bytes(receipt_path.read_bytes()) == existing["sha256"], "existing receipt hash mismatch")
            validate_bound_decision(_read(manifest_path), _read(receipt_path))
            continue
        decision = pending_observation_decision(manifest_path)
        _require(decision["bundle_id"] == row["bundle_id"], "catalog bundle identity mismatch")
        relative = f"{row['model_family_id']}/{row['model_version_id']}/{row['bundle_id']}.json"
        path = output_root / relative
        encoded = canonical_json_bytes(decision)
        _require(not path.exists() or path.read_bytes() == encoded, "immutable companion receipt collision")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        records[row["bundle_id"]] = {
            "run_id": decision["run_id"], "bundle_id": decision["bundle_id"],
            "status": decision["status"], "verdict": decision["verdict"],
            "path": relative, "sha256": sha256_bytes(encoded), "byte_size": len(encoded),
        }
    ordered = sorted(records.values(), key=lambda row: (row["run_id"], row["bundle_id"]))
    if index["records"] != ordered or "generated_at" not in index:
        index["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index["records"] = ordered
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = index_path.with_suffix(".json.tmp")
    temporary.write_bytes(canonical_json_bytes(index))
    temporary.replace(index_path)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--formal-catalog", type=Path)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.formal_catalog:
        if args.manifest or args.draft or args.receipt:
            parser.error("--formal-catalog cannot be combined with draft receipt options")
        catalog = materialize_pending_observation_decisions(catalog_path=args.formal_catalog, output_root=args.output)
        print(json.dumps({"receipt_count": len(catalog["records"]), "research_only": True, "trade_ready": False}))
        return
    if not args.manifest or not args.draft:
        parser.error("--manifest and --draft are required without --formal-catalog")
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
