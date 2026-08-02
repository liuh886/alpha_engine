"""Compare two immutable selected-pool provider snapshots and evidence packs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.data.provider_snapshot_comparison import (
    compare_candidate_evidence,
    compare_refresh_manifests,
    decide_snapshot_drift,
    load_json,
    sha256_file,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-refresh-manifest", type=Path, required=True)
    parser.add_argument("--new-refresh-manifest", type=Path, required=True)
    parser.add_argument("--old-provider-manifest", type=Path, required=True)
    parser.add_argument("--new-provider-manifest", type=Path, required=True)
    parser.add_argument("--old-stability", type=Path, default=None)
    parser.add_argument("--new-stability", type=Path, default=None)
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    old_refresh = load_json(args.old_refresh_manifest)
    new_refresh = load_json(args.new_refresh_manifest)
    old_provider = load_json(args.old_provider_manifest)
    new_provider = load_json(args.new_provider_manifest)

    rows, summary = compare_refresh_manifests(old_refresh, new_refresh)
    summary["provider_manifests"] = {
        "old": {
            "path": str(args.old_provider_manifest),
            "sha256": sha256_file(args.old_provider_manifest),
            "provider_identity_sha256": old_provider.get("provider_identity_sha256"),
            "calendar": old_provider.get("calendar"),
            "features_sha256": old_provider.get("features_sha256"),
            "source_csv_count": len(old_provider.get("source_csvs", [])),
        },
        "new": {
            "path": str(args.new_provider_manifest),
            "sha256": sha256_file(args.new_provider_manifest),
            "provider_identity_sha256": new_provider.get("provider_identity_sha256"),
            "calendar": new_provider.get("calendar"),
            "features_sha256": new_provider.get("features_sha256"),
            "source_csv_count": len(new_provider.get("source_csvs", [])),
        },
    }

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "symbol_snapshot_diff.csv"
    dictionaries = [row.to_dict() for row in rows]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dictionaries[0]) if dictionaries else [])
        if dictionaries:
            writer.writeheader()
            writer.writerows(dictionaries)

    evidence: dict[str, object] | None = None
    if args.old_stability or args.new_stability or args.candidate_id:
        if not (args.old_stability and args.new_stability and args.candidate_id):
            raise ValueError(
                "old/new stability files and candidate-id must be supplied together"
            )
        evidence = compare_candidate_evidence(
            load_json(args.old_stability),
            load_json(args.new_stability),
            candidate_id=str(args.candidate_id),
        )
        _write_json(output / "candidate_evidence_diff.json", evidence)

    decision = decide_snapshot_drift(rows, summary)
    result = {
        "schema_version": "1.0",
        "summary": summary,
        "candidate_evidence": evidence,
        "decision": decision,
        "inputs": {
            "old_refresh_manifest_sha256": sha256_file(args.old_refresh_manifest),
            "new_refresh_manifest_sha256": sha256_file(args.new_refresh_manifest),
            "old_provider_manifest_sha256": sha256_file(args.old_provider_manifest),
            "new_provider_manifest_sha256": sha256_file(args.new_provider_manifest),
        },
        "outputs": {
            "symbol_snapshot_diff": str(csv_path),
        },
    }
    _write_json(output / "snapshot_comparison.json", result)
    _write_json(output / "decision.json", decision)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
