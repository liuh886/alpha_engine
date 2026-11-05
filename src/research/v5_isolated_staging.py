"""Isolated, hash-bound v5 market-history staging for local or Colab research.

This never changes the immutable v5 source nor overlays a Git checkout.
It is a *data-root adapter*, not a second provider or entitlement mechanism.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from src.research.cloud_exchange import ExchangeError
from src.research.e1a_price_preflight import inspect as inspect_price

STAGE_RECEIPT = ".p2-v5-stage.json"
HEX = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _safe(relative: str) -> Path:
    path = PurePosixPath(relative)
    if (not relative or not relative.startswith(("configs/", "data/")) or
            "\\" in relative or ":" in relative or path.is_absolute() or
            any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ExchangeError("invalid staged path")
    return Path(*path.parts)


def stage(*, manifest: Path, archive: Path, expected_manifest_sha: str,
          expected_archive_sha: str, output_root: Path) -> dict[str, Any]:
    """Create a new standalone source root with only verified v5 files."""
    checkout = Path(__file__).resolve().parents[2]
    root = output_root.resolve()
    if root.exists() or root.is_relative_to(checkout):
        raise ExchangeError("stage destination must be new and outside Git checkout")
    verified = inspect_price(
        manifest_path=manifest, archive_path=archive,
        expected_manifest_sha256=expected_manifest_sha,
        expected_archive_sha256=expected_archive_sha)
    if verified["data_status"] != "VERIFIED_US87_COMPLETE_RETAINED_PRICE_DOMAIN":
        raise ExchangeError("US87 market history not verified")
    with zipfile.ZipFile(archive) as z:
        index = json.loads(z.read("manifest.json"))
        entries = index["files"]
        files: list[dict[str, Any]] = []
        for row in entries:
            relative = _safe(str(row["path"]))
            if z.getinfo("files/" + row["path"]).file_size != row["size"]:
                raise ExchangeError("member size changed during staging")
            files.append({"path": relative.as_posix(),
                          "sha256": row["sha256"], "size_bytes": row["size"]})
        if not files:
            raise ExchangeError("no staged data")
        root.mkdir(parents=True, exist_ok=False)
        for row in files:
            target = root / _safe(row["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open("files/" + row["path"]) as src, target.open("xb") as dst:
                h = hashlib.sha256()
                n = 0
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            if n != row["size_bytes"] or h.hexdigest() != row["sha256"]:
                raise ExchangeError("staged source byte mismatch")
    receipt = {
        "schema_version": "p2_v5_isolated_research_root_v1",
        "market": "us", "pool_id": "us_selected_equities_v2",
        "bundle_manifest_sha256": expected_manifest_sha,
        "history_archive_sha256": expected_archive_sha,
        "source_producer_revision": verified["source_producer_revision"],
        "data_cutoff": verified["data_cutoff"],
        "files": files, "research_only": True, "trade_ready": False,
        "pit_certified": False, "cloud_processing_rights_granted": False,
        "model_executed": False,
    }
    (root / STAGE_RECEIPT).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_stage(root)
    return {"status": "STAGED_DATA_ONLY", "staged_root": str(root),
            "files": len(files), "data_cutoff": receipt["data_cutoff"],
            "history_archive_sha256": expected_archive_sha,
            "cloud_processing_rights_granted": False}


def verify_stage(root: Path) -> dict:
    """Rescan all bounded data bytes; reject missing, altered or injected files."""
    root = root.resolve()
    receipt_path = root / STAGE_RECEIPT
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ExchangeError("missing staged source receipt")
    doc = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (doc.get("schema_version") != "p2_v5_isolated_research_root_v1" or
            doc.get("market") != "us" or doc.get("pool_id") != "us_selected_equities_v2" or
            doc.get("research_only") is not True or doc.get("trade_ready") is not False or
            doc.get("pit_certified") is not False or
            doc.get("cloud_processing_rights_granted") is not False or
            doc.get("model_executed") is not False or
            not isinstance(doc.get("files"), list) or not doc["files"]):
        raise ExchangeError("invalid staged research boundary")
    expected: set[str] = set()
    for row in doc["files"]:
        rel = _safe(row["path"]).as_posix()
        if rel in expected or not HEX.fullmatch(row["sha256"]):
            raise ExchangeError("duplicate or invalid staged entry")
        expected.add(rel)
        f = root / rel
        if (f.is_symlink() or not f.is_file() or f.stat().st_size != row["size_bytes"]
                or _sha256(f) != row["sha256"]):
            raise ExchangeError(f"altered or missing staged research input: {rel}")
    found = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if found != expected | {STAGE_RECEIPT}:
        raise ExchangeError("unexpected or missing staged input")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    make = sub.add_parser("stage")
    make.add_argument("--manifest", required=True, type=Path)
    make.add_argument("--archive", required=True, type=Path)
    make.add_argument("--expected-manifest-sha256", required=True)
    make.add_argument("--expected-archive-sha256", required=True)
    make.add_argument("--output-root", required=True, type=Path)
    check = sub.add_parser("verify")
    check.add_argument("--root", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        result = (stage(manifest=args.manifest, archive=args.archive,
                        expected_manifest_sha=args.expected_manifest_sha256,
                        expected_archive_sha=args.expected_archive_sha256,
                        output_root=args.output_root)
                  if args.action == "stage"
                  else {"status": "VERIFIED_DATA_ONLY", "receipt": verify_stage(args.root)})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"BLOCKED_V5_STAGING: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
