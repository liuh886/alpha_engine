#!/usr/bin/env python3
"""Promote reviewed selected-pool repair files into canonical source storage.

Promotion is permitted only when approved targets are present in an immutable
repair artifact and match the committed approval manifest byte-for-byte.
Existing canonical files are never replaced by this path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE_PATH = Path("artifacts/selected_pool_price_refresh_manifest.json")
CANONICAL_SOURCE_ROOT = PROJECT_ROOT / "data" / "csv_source"
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "research_source_repair"


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


def _require_equal(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        raise ValueError(f"{label} mismatch: expected={expected!r} observed={observed!r}")


def promote(
    *,
    approval_path: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    approval = _load_json(approval_path)
    _require_equal(
        "approval_status",
        approval.get("approval_status"),
        "approved_for_canonical_missing_source_addition",
    )
    experiment_id = str(approval["experiment_id"])
    market = str(approval["market"])
    approved_targets = approval.get("targets")
    if not isinstance(approved_targets, dict) or not approved_targets:
        raise ValueError("approval targets must be a non-empty object")

    source_artifact = approval.get("source_artifact")
    if not isinstance(source_artifact, dict):
        raise ValueError("approval source_artifact must be an object")
    archive_root_raw = str(source_artifact.get("archive_root", "")).strip()
    if not archive_root_raw:
        raise ValueError("approval source_artifact.archive_root is required")
    archive_root = Path(archive_root_raw)
    if archive_root.is_absolute() or ".." in archive_root.parts:
        raise ValueError("approval source_artifact.archive_root must be repository-relative")
    artifact_root_resolved = artifact_root.resolve()
    repair_root = (artifact_root_resolved / archive_root / experiment_id).resolve()
    repair_root.relative_to(artifact_root_resolved)

    refresh_manifest = _load_json(repair_root / MANIFEST_RELATIVE_PATH)
    _require_equal(
        "refresh_status",
        refresh_manifest.get("status"),
        "selected_pool_price_refresh_ready",
    )
    _require_equal("market", refresh_manifest.get("market"), market)
    _require_equal(
        "refresh_mode", refresh_manifest.get("refresh_mode"), "repair_only"
    )
    _require_equal(
        "requested_start", refresh_manifest.get("start"), approval.get("requested_start")
    )
    _require_equal(
        "requested_end", refresh_manifest.get("cutoff"), approval.get("requested_end")
    )
    refresh_targets = set(refresh_manifest.get("targets", []))
    unbound_targets = sorted(set(approved_targets) - refresh_targets)
    if unbound_targets:
        raise ValueError(
            "approval targets are absent from immutable repair artifact: "
            f"{unbound_targets}"
        )

    records = {
        str(record.get("symbol")): record
        for record in refresh_manifest.get("records", [])
        if isinstance(record, dict)
    }
    copied: list[dict[str, Any]] = []
    already_present: list[str] = []

    for symbol, expected_raw in sorted(approved_targets.items()):
        if not isinstance(expected_raw, dict):
            raise ValueError(f"approval target {symbol} must be an object")
        expected = dict(expected_raw)
        record = records.get(symbol)
        if record is None:
            raise ValueError(f"refresh manifest has no record for {symbol}")
        _require_equal(f"{symbol}.action", record.get("action"), "fetched_replacement")
        for field in (
            "provider",
            "provider_symbol",
            "rows",
            "first_date",
            "last_date",
        ):
            _require_equal(f"{symbol}.{field}", record.get(field), expected.get(field))
        _require_equal(
            f"{symbol}.sha256", record.get("output_sha256"), expected.get("sha256")
        )

        if symbol == "TIGO":
            identity = record.get("identity_contract") or {}
            _require_equal(
                "TIGO.expected_issuer",
                identity.get("expected_issuer"),
                expected.get("expected_issuer"),
            )
            _require_equal(
                "TIGO.forbidden_substitute",
                identity.get("forbidden_substitute"),
                expected.get("forbidden_substitute"),
            )

        candidate = repair_root / "data" / "csv_source" / f"{symbol}.csv"
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        candidate_sha = _sha256(candidate)
        _require_equal(f"{symbol}.artifact_sha256", candidate_sha, expected.get("sha256"))

        destination = CANONICAL_SOURCE_ROOT / f"{symbol}.csv"
        if destination.exists():
            if _sha256(destination) != candidate_sha:
                raise ValueError(
                    f"canonical source already exists with different content: {symbol}"
                )
            already_present.append(symbol)
            continue
        shutil.copy2(candidate, destination)
        copied.append(
            {
                "symbol": symbol,
                "sha256": candidate_sha,
                "rows": expected["rows"],
                "first_date": expected["first_date"],
                "last_date": expected["last_date"],
            }
        )

    receipt = {
        "schema_version": "1.0",
        "repair_id": approval["repair_id"],
        "experiment_id": experiment_id,
        "market": market,
        "status": "approved_source_repair_promoted",
        "copied": copied,
        "already_present": already_present,
    }
    receipt_path = repair_root / "artifacts" / "source_repair_promotion_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    args = parser.parse_args()

    receipt = promote(
        approval_path=args.approval.resolve(),
        artifact_root=args.artifact_root.resolve(),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
