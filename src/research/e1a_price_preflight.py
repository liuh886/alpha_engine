"""E1-A: inspect v5 full-US87 daily-price source before any Colab compute.

The existing v5 ZIP is p2_local_market_history_v1, NOT an
alpha_research_exchange_v1 package. Read it without stage/overwrite.
Frozen local-only/source-rights flags remain unchanged. This validates data
and records a separate *operator attestation*; it is not a license or model
execution authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError
from src.research.comprehensive_bundle import verify_local_history

BUNDLE_SCHEMA = "p2_local_research_bundle_v2"
HISTORY_SCHEMA = "p2_local_market_history_v1"
RIGHTS_SCHEMA = "e1a_price_cloud_rights_v1"
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _regular(path: Path) -> Path:
    if not path.is_file() or path.is_symlink():
        raise ExchangeError(f"missing or symlinked input: {path.name}")
    return path


def _rights(path: Path | None, *, market: str, bundle_sha: str, history_sha: str) -> dict:
    if path is None:
        return {"status": "BLOCKED_NO_PER_SOURCE_CLOUD_RIGHTS_RECORD"}
    source = json.loads(_regular(path).read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ExchangeError("cloud rights record must be a JSON object")
    keys = ("schema_version", "market", "bundle_manifest_sha256", "history_archive_sha256",
            "cloud_processing_purpose", "owner_approved_private_cloud_processing",
            "provider_rights", "reviewed_at")
    if (source.get("schema_version") != RIGHTS_SCHEMA or source.get("market") != market or
            source.get("bundle_manifest_sha256") != bundle_sha or
            source.get("history_archive_sha256") != history_sha or
            source.get("cloud_processing_purpose") != "private_colab_daily_price_research" or
            source.get("owner_approved_private_cloud_processing") is not True or
            not all(k in source for k in keys)):
        raise ExchangeError("cloud rights record lacks exact owner consent and data bindings")
    provider_rights = source.get("provider_rights")
    if not isinstance(provider_rights, list) or not provider_rights:
        raise ExchangeError("cloud rights must list each actual source provider")
    for row in provider_rights:
        if (not isinstance(row, dict) or not isinstance(row.get("provider"), str) or
                not row["provider"].strip() or not isinstance(row.get("terms_url"), str) or
                not row["terms_url"].startswith("https://") or
                row.get("private_cloud_compute_permitted") is not True or
                not isinstance(row.get("review_basis"), str) or
                len(row["review_basis"].strip()) < 12):
            raise ExchangeError("provider rights record lacks explicit checked terms/basis")
    if not isinstance(source.get("reviewed_at"), str) or not source["reviewed_at"].strip():
        raise ExchangeError("rights review date must be explicit")
    # This is the owner's bounded declaration, NOT independent vendor certification.
    return {"status": "OWNER_ATTESTATION_RECORDED_NOT_VENDOR_CERTIFIED",
            "provider_count": len(provider_rights), "record_sha256": _hash(path)}


def inspect(*, manifest_path: Path, archive_path: Path, expected_manifest_sha256: str,
            expected_archive_sha256: str, market: str = "us",
            rights_record: Path | None = None) -> dict[str, Any]:
    """Check real v5 bytes and its complete US87 history contract, without extraction."""
    if market != "us":
        raise ExchangeError("E1-A is US87 price only; CN needs a separate study")
    if not HEX_SHA256.fullmatch(expected_manifest_sha256) or not HEX_SHA256.fullmatch(
            expected_archive_sha256):
        raise ExchangeError("two explicit expected SHA256 digests required")
    manifest_path = _regular(manifest_path)
    archive_path = _regular(archive_path)
    actual_manifest_sha = _hash(manifest_path)
    actual_archive_sha = _hash(archive_path)
    if actual_manifest_sha != expected_manifest_sha256 or actual_archive_sha != expected_archive_sha256:
        raise ExchangeError("cloud input SHA differs from independently pinned reference")
    aggregate = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (aggregate.get("schema_version") != BUNDLE_SCHEMA or
            aggregate.get("status") != "PARTIAL" or
            aggregate.get("research_only") is not True or
            aggregate.get("trade_ready") is not False or
            aggregate.get("pit_certified") is not False or
            aggregate.get("colab_executed") is not False or
            aggregate.get("transfer_scope") != "local_only" or
            aggregate.get("owner_approved_private_cloud_copy") is not False):
        raise ExchangeError("invalid immutable v5 local-only boundary")
    entries = aggregate.get("files")
    if not isinstance(entries, list):
        raise ExchangeError("v5 source manifest is missing")
    matched = [f for f in entries if isinstance(f, dict) and f.get("path") == "us_market_history.zip"]
    if (len(matched) != 1 or matched[0].get("sha256") != actual_archive_sha or
            matched[0].get("size_bytes") != archive_path.stat().st_size):
        raise ExchangeError("US history not bound to the frozen aggregate manifest")
    history = verify_local_history(archive_path)
    if (history.get("schema_version") != HISTORY_SCHEMA or
            history.get("market") != "us" or
            history.get("pool_id") != "us_selected_equities_v2" or
            history.get("candidate_count") != 87 or
            history.get("repo_revision") != aggregate.get("repo_revision") or
            history.get("data_cutoff") != "2026-11-03" or
            history.get("research_only") is not True or
            history.get("trade_ready") is not False or
            history.get("pit_certified") is not False):
        raise ExchangeError("US87 roster, cutoff or producer identity mismatch")
    rights = _rights(rights_record, market=market, bundle_sha=actual_manifest_sha,
                     history_sha=actual_archive_sha)
    return {"schema_version": "e1a_v5_price_preflight_v1",
            "data_status": "VERIFIED_US87_COMPLETE_RETAINED_PRICE_DOMAIN",
            "cloud_execution_rights": rights,
            "bundle_manifest_sha256": actual_manifest_sha,
            "archive_sha256": actual_archive_sha, "archive_size_bytes": archive_path.stat().st_size,
            "pool_id": history["pool_id"], "candidate_count": 87,
            "reference_symbols": history.get("reference_symbols", []),
            "data_cutoff": history["data_cutoff"],
            "source_producer_revision": history["repo_revision"],
            "source_frozen_local_only": True,
            "model_execution_authorized": False, "pit_certified": False,
            "trade_ready": False, "colab_executed": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--expected-manifest-sha256", required=True)
    p.add_argument("--expected-archive-sha256", required=True)
    p.add_argument("--market", choices=("us",), default="us")
    p.add_argument("--rights-record", type=Path)
    p.add_argument("--require-cloud-rights", action="store_true")
    args = p.parse_args(argv)
    try:
        result = inspect(manifest_path=args.manifest, archive_path=args.archive,
                         expected_manifest_sha256=args.expected_manifest_sha256,
                         expected_archive_sha256=args.expected_archive_sha256,
                         market=args.market, rights_record=args.rights_record)
        print(json.dumps(result, indent=2))
        if args.require_cloud_rights and result["cloud_execution_rights"]["status"].startswith("BLOCKED"):
            return 11
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"BLOCKED_E1A_PRICE_PREFLIGHT: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
