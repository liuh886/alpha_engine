"""Recover exact, hash-pinned research source ZIPs already registered by Alpha Engine.

This is a manual local data-access tool. It does not invoke Colab, grant market
data redistribution rights, or upload to Drive or GitHub Pages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError

RECEIPT = Path(
    "data/research/model_data_bundle_v1/sources/governed-source-receipt.json"
)
ALLOWED = frozenset(("us_events", "cn_events", "cn_alpha158", "qqq_reference"))
ARCHIVE_REPO = "liuh886/alpha-engine-data-archive"
SOURCE_REPO = "liuh886/alpha_engine"


def _source_plan(root: Path) -> dict[str, dict]:
    record = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    sources = {}
    for item in record.get("sources", []):
        source_id = item.get("source_id")
        if source_id not in ALLOWED:
            continue
        expected = str(item.get("artifact_digest", "")).removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ExchangeError(f"missing exact SHA for {source_id}")
        git = item.get("durable_git")
        release = item.get("durable_release")
        if git:
            if git.get("repository") != ARCHIVE_REPO:
                raise ExchangeError("unexpected archive repository")
            revision = git.get("commit")
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ExchangeError("unverified archive commit")
            path = git.get("path")
            if not isinstance(path, str) or not re.fullmatch(r"archives/[a-zA-Z0-9_.-]+\.zip", path):
                raise ExchangeError("unsafe archive path")
            if git.get("sha256") != expected:
                raise ExchangeError("archive sha differs from canonical source receipt")
            url = f"https://raw.githubusercontent.com/{ARCHIVE_REPO}/{revision}/{path}"
            size = git.get("size_bytes")
        elif release:
            tag = release.get("tag")
            name = release.get("asset_name")
            if (not isinstance(tag, str) or not re.fullmatch(r"model-data-source-[a-zA-Z0-9_.-]+", tag)
                    or not isinstance(name, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.zip", name)):
                raise ExchangeError("unsafe release locator")
            if release.get("sha256") != expected:
                raise ExchangeError("release sha differs from canonical source receipt")
            url = (f"https://github.com/{SOURCE_REPO}/releases/download/"
                   f"{tag}/{name}")
            size = release.get("size_bytes")
        else:
            raise ExchangeError(f"source {source_id} has no pinned durable archive")
        if not isinstance(size, int) or size <= 0:
            raise ExchangeError("archive size missing")
        sources[source_id] = {
            "source_id": source_id,
            "source_kind": item.get("source_kind"),
            "url": url,
            "sha256": expected,
            "size_bytes": size,
            "local_filename": f"{source_id}.zip",
            "market": item.get("market"),
            "cutoff": item.get("evidence_cutoff"),
        }
    if set(sources) != ALLOWED:
        raise ExchangeError(f"missing source archive: {sorted(ALLOWED - set(sources))}")
    return sources


def verify_archive(path: Path, record: dict) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ExchangeError(f"missing source ZIP: {path}")
    if path.stat().st_size != record["size_bytes"]:
        raise ExchangeError(f"source archive length mismatch: {record['source_id']}")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != record["sha256"]:
        raise ExchangeError(f"source archive hash mismatch: {record['source_id']}")
    if not zipfile.is_zipfile(path):
        raise ExchangeError(f"source archive is not a valid ZIP: {record['source_id']}")
    return {"source_id": record["source_id"], "status": "VERIFIED",
            "path": str(path), "sha256": sha.hexdigest(),
            "size_bytes": path.stat().st_size, "market": record["market"]}


def fetch_archive(destination: Path, record: dict) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / record["local_filename"]
    if target.exists():
        return verify_archive(target, record)
    partial = destination / (record["local_filename"] + ".partial")
    if partial.exists():
        raise ExchangeError(f"prior partial download exists, inspect and remove it: {partial}")
    created = False
    try:
        req = urllib.request.Request(
            record["url"],
            headers={"User-Agent": "AlphaEngine-ResearchSourceRecovery/1.0"},
        )
        with partial.open("xb") as out:
            created = True
            with urllib.request.urlopen(req, timeout=120) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    out.write(chunk)
                    if out.tell() > record["size_bytes"]:
                        raise ExchangeError("unexpected oversized source archive")
        verify_archive(partial, record)
        if target.exists():
            raise ExchangeError("download target concurrently created; not overwriting")
        partial.rename(target)
        return verify_archive(target, record)
    except Exception:
        if created:
            partial.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover existing pinned original sources locally")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("list", "verify", "fetch"):
        command = sub.add_parser(name)
        command.add_argument("--repo-root", type=Path, default=Path("."))
        command.add_argument("--destination", type=Path)
        command.add_argument("--source", choices=("all", *sorted(ALLOWED)), default="all")
    args = parser.parse_args(argv)
    try:
        catalog = _source_plan(args.repo_root.resolve())
        targets = catalog.values() if args.source == "all" else [catalog[args.source]]
        if args.action == "list":
            print(json.dumps({"sources": list(targets), "status": "PINNED_NOT_DOWNLOADED"},
                             indent=2))
            return 0
        if args.destination is None:
            raise ExchangeError("--destination is required for verify or fetch")
        root = args.repo_root.resolve()
        destination = args.destination.resolve()
        if destination.is_relative_to(root):
            raise ExchangeError("download destination must be outside public Git repository")
        output = []
        for record in targets:
            if args.action == "verify":
                output.append(verify_archive(destination / record["local_filename"], record))
            else:
                output.append(fetch_archive(destination, record))
        print(json.dumps({"sources": output}, indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, urllib.error.URLError,
            json.JSONDecodeError) as exc:
        print(f"BLOCKED_SOURCE_RECOVERY: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
