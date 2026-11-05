"""Recover exact, hash-pinned research source ZIPs already registered by Alpha Engine.

This is a manual local data-access tool. It does not invoke Colab, grant market
data redistribution rights, or upload to Drive or GitHub Pages.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

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
            locator = {"github_api_path":
                       f"repos/{ARCHIVE_REPO}/contents/{path}?ref={revision}"}
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
            locator = {"github_release_tag": tag, "github_asset_name": name}
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
            **locator,
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
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 10000:
            raise ExchangeError("duplicate or excessive source archive members")
        for info in archive.infolist():
            name = info.filename
            if ("\\" in name or ":" in name or name.startswith("/") or
                    ".." in name.split("/") or
                    (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ExchangeError("unsafe source archive member")
        if sum(info.file_size for info in archive.infolist()) > 2 * 1024**3:
            raise ExchangeError("expanded source archive exceeds limit")
        if archive.testzip() is not None:
            raise ExchangeError("source archive CRC mismatch")
    return {"source_id": record["source_id"], "status": "VERIFIED",
            "path": str(path), "sha256": sha.hexdigest(),
            "size_bytes": path.stat().st_size, "market": record["market"],
            "member_count": len(names)}


def _github_metadata(endpoint: str) -> dict:
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, timeout=120)
    if result.returncode:
        raise ExchangeError("authenticated GitHub metadata request failed")
    return json.loads(result.stdout)


def _github_download(record: dict, output: BinaryIO) -> None:
    """Use gh's existing authentication without extracting or logging a token."""

    if record.get("github_api_path"):
        entry = _github_metadata(record["github_api_path"])
        if entry.get("size") != record["size_bytes"] or entry.get("type") != "file":
            raise ExchangeError("pinned Git source size/type mismatch")
        # gh's raw output renderer can transform non-UTF8 ZIP bytes on Windows.
        # The authenticated blob JSON endpoint transports base64 losslessly.
        blob = _github_metadata(f"repos/{ARCHIVE_REPO}/git/blobs/{entry['sha']}")
        if blob.get("encoding") != "base64" or blob.get("size") != record["size_bytes"]:
            raise ExchangeError("pinned Git blob metadata mismatch")
        output.write(base64.b64decode(blob["content"]))
    else:
        release = _github_metadata(
            f"repos/{SOURCE_REPO}/releases/tags/{record['github_release_tag']}"
        )
        assets = [a for a in release.get("assets", [])
                  if a.get("name") == record["github_asset_name"]]
        if (len(assets) != 1 or assets[0].get("size") != record["size_bytes"] or
                assets[0].get("digest") != "sha256:" + record["sha256"]):
            raise ExchangeError("exact release asset identity mismatch")
        result = subprocess.run(
            ["gh", "api", f"repos/{SOURCE_REPO}/releases/assets/{assets[0]['id']}",
             "-H", "Accept: application/octet-stream"],
            stdout=output, stderr=subprocess.PIPE, timeout=600,
        )
        if result.returncode:
            raise ExchangeError("authenticated GitHub asset download failed")


def inspect_market_archive(root: Path, path: Path, record: dict) -> dict:
    """Admit an extra provider archive only by exact canonical per-symbol CSV SHA."""
    verify_archive(path, {**record, 'source_id': 'market_source_' + record['market']})
    market = record['market']
    base = root / f'data/research/market_evidence/{market}'
    catalog = json.loads((base / 'catalog.json').read_text(encoding='utf-8'))
    results = []
    with zipfile.ZipFile(path) as archive:
        csvs = {}
        for name in archive.namelist():
            if '/csv_source/' in name and name.endswith('.csv'):
                symbol = Path(name).stem
                if symbol in csvs:
                    raise ExchangeError('duplicate provider source CSV identity')
                csvs[symbol] = name
        for security in catalog['symbols']:
            symbol = str(security['symbol'])
            payload = json.loads((base / security['path']).read_text(encoding='utf-8'))
            name = csvs.get(symbol)
            observed = hashlib.sha256(archive.read(name)).hexdigest() if name else None
            expected = payload['source_csv_sha256']
            if observed != expected:
                raise ExchangeError(f'exact market source CSV mismatch: {market}/{symbol}')
            results.append({'symbol': symbol, 'member': name, 'sha256': observed,
                            'expected_sha256': expected, 'status': 'VERIFIED'})
    return {**record, 'cutoff': catalog['cutoff'], 'verified_symbols': len(results), 'records': results}


def fetch_market_archives(root: Path, destination: Path, run_id: int) -> dict:
    if destination.resolve().is_relative_to(root.resolve()) or run_id <= 0:
        raise ExchangeError('market sources require a private destination and explicit run id')
    entries = _github_metadata(f'repos/{SOURCE_REPO}/actions/runs/{run_id}/artifacts')['artifacts']
    destination.mkdir(parents=True, exist_ok=True)
    output = []
    for market in ('us', 'cn'):
        matches = [a for a in entries if a['name'] == f'formal-provider-{market}-{run_id}']
        if len(matches) != 1 or matches[0]['expired']:
            raise ExchangeError('exact market provider archive unavailable')
        source = matches[0]
        digest = str(source.get('digest', '')).removeprefix('sha256:')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ExchangeError('market provider archive digest missing')
        record = {'market': market, 'run_id': run_id, 'artifact_id': source['id'],
                  'archive': f'market_source_{market}_{run_id}.zip', 'sha256': digest,
                  'size_bytes': source['size_in_bytes']}
        target = destination / record['archive']
        if not target.exists():
            partial = target.with_suffix('.zip.partial')
            with partial.open('xb') as out:
                result = subprocess.run(
                    ['gh', 'api', f"repos/{SOURCE_REPO}/actions/artifacts/{source['id']}/zip"],
                    stdout=out, stderr=subprocess.PIPE, timeout=600)
            if result.returncode:
                raise ExchangeError('exact market provider archive download failed; partial retained')
            inspect_market_archive(root, partial, record)
            partial.rename(target)
        output.append(inspect_market_archive(root, target, record))
    return {'market_source_archives': output, 'source_selection': 'explicit_run_and_exact_existing_csv_hashes'}


def fetch_archive(destination: Path, record: dict, *, github_cli: bool = False) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / record["local_filename"]
    if target.exists():
        return verify_archive(target, record)
    partial = destination / (record["local_filename"] + ".partial")
    if partial.exists():
        raise ExchangeError(f"prior partial download exists, inspect and remove it: {partial}")
    created = False
    try:
        if github_cli:
            with partial.open("xb") as out:
                created = True
                _github_download(record, out)
        else:
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
        command.add_argument("--github-cli", action="store_true",
                             help="Use existing authenticated gh session for exact archives")
    market_fetch = sub.add_parser('fetch-market')
    market_fetch.add_argument('--repo-root', type=Path, default=Path('.'))
    market_fetch.add_argument('--destination', type=Path, required=True)
    market_fetch.add_argument('--run-id', type=int, required=True)
    market_fetch.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'fetch-market':
            result = fetch_market_archives(args.repo_root, args.destination, args.run_id)
            if args.report.resolve().is_relative_to(args.repo_root.resolve()):
                raise ExchangeError('physical source recovery report must remain private')
            with args.report.open('x', encoding='utf-8') as out:
                json.dump(result, out, indent=2)
            print(json.dumps({'markets': [{'market': r['market'], 'verified_symbols': r['verified_symbols'],
                                          'archive_sha256': r['sha256']} for r in result['market_source_archives']]}, indent=2))
            return 0
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
                output.append(fetch_archive(destination, record, github_cli=args.github_cli))
        print(json.dumps({"sources": output}, indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, urllib.error.URLError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError) as exc:
        print(f"BLOCKED_SOURCE_RECOVERY: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
