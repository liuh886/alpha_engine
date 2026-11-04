"""Private, manifest-bound transport between local Alpha Engine and transient Colab workers.

No Drive API, database, broker, public frontend publication, or strategy execution.
Packages are untrusted until verified; file paths and rights must be explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

VERSION = "alpha_research_exchange_v1"
MAX_FILES = 256
MAX_BYTES = 2 * 1024**3
ALLOWED_PREFIXES = (
    "data/csv_clean/",
    "data/qlib_data/",
    "data/research/model_data_bundle_v1/",
    "data/research/market_evidence/",
    "configs/research_universes/",
    "configs/research_experiments/",
    "artifacts/research_studies/",
)
DENIED_PARTS = {
    ".git", ".env", "credentials", "secrets", "private", "account",
    "token", "strategy_operations", "strategy_signal_ledgers",
    "model_operations", "model_decisions", "__pycache__",
}
POOLS = {
    "us_selected_equities_v2": "configs/research_universes/us_selected_equities_v2.yaml",
    "cn_selected_equities_v3": "configs/research_universes/cn_selected_equities_v3.yaml",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ExchangeError(ValueError):
    """A source, integrity, rights, or safe-import gate failed."""


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ExchangeError(f"{name} must be a pinned sha256")
    return value


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ExchangeError("invalid relative path")
    path = Path(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ExchangeError(f"unsafe relative path: {value}")
    blocked_fragments = (
        "secret", "credential", "token", ".env", "api_key", "broker", "ibkr",
        "account", "private", "strategy_operation", "signal_ledger",
    )
    if path.as_posix() != value or any(
        part.lower() in DENIED_PARTS or any(flag in part.lower() for flag in blocked_fragments)
        for part in path.parts
    ):
        raise ExchangeError(f"forbidden research path: {value}")
    if not value.startswith(ALLOWED_PREFIXES):
        raise ExchangeError(f"path not in approved research prefixes: {value}")
    return value


def _safe_target(root: Path, name: str) -> Path:
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()):
        raise ExchangeError(f"path escapes checkout: {name}")
    return target


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ExchangeError("a Git checkout is required to pin execution code") from exc


def _checked_recipe(recipe: dict[str, Any], root: Path) -> dict[str, Any]:
    required = {
        "schema_version", "study_id", "market", "pool_id", "data_cutoff",
        "repo_revision", "source_manifest_path", "source_manifest_sha256",
        "owner_approved_private_cloud_copy", "rights_class", "inputs",
    }
    if set(recipe) != required:
        raise ExchangeError(f"recipe fields differ: {sorted(set(recipe) ^ required)}")
    if recipe["schema_version"] != VERSION:
        raise ExchangeError("unsupported recipe version")
    if recipe["owner_approved_private_cloud_copy"] is not True:
        raise ExchangeError("manual approval of private cloud transfer is required")
    if recipe["rights_class"] != "private_cloud_research_allowed":
        raise ExchangeError("source rights not cleared for private Drive transfer")
    if recipe["market"] not in {"us", "cn"} or recipe["pool_id"] not in POOLS:
        raise ExchangeError("unsupported governed pool")
    if (recipe["market"] == "us") != recipe["pool_id"].startswith("us_"):
        raise ExchangeError("market/pool mismatch")
    if not isinstance(recipe["study_id"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{2,79}", recipe["study_id"]
    ):
        raise ExchangeError("invalid study id")
    from datetime import date

    try:
        date.fromisoformat(recipe["data_cutoff"])
    except (TypeError, ValueError) as exc:
        raise ExchangeError("data_cutoff must be ISO YYYY-MM-DD") from exc
    revision = recipe["repo_revision"]
    if not isinstance(revision, str) or not COMMIT_RE.fullmatch(revision):
        raise ExchangeError("repo_revision must be a full commit sha")
    if _git_head(root) != revision:
        raise ExchangeError("recipe repo revision does not match local checkout")
    source_path = _safe_name(recipe["source_manifest_path"])
    source_sha = _sha(recipe["source_manifest_sha256"], "source_manifest_sha256")
    entries = recipe["inputs"]
    if not isinstance(entries, list) or len(entries) < 3 or len(entries) > MAX_FILES:
        raise ExchangeError("input list must include pool, source manifest and data")
    recorded: list[dict[str, Any]] = []
    seen: set[str] = set()
    roles: set[str] = set()
    total_size = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "role"}:
            raise ExchangeError("each input needs path, sha256 and role")
        name = _safe_name(entry["path"])
        if name in seen:
            raise ExchangeError(f"duplicate input: {name}")
        seen.add(name)
        role = entry["role"]
        if role not in {"pool_spec", "source_manifest", "data", "study_spec"}:
            raise ExchangeError(f"invalid input role: {role}")
        roles.add(role)
        expected = _sha(entry["sha256"], f"sha256:{name}")
        file = _safe_target(root, name)
        if not file.is_file() or file.is_symlink():
            raise ExchangeError(f"missing or symlinked input: {name}")
        size = file.stat().st_size
        total_size += size
        if total_size > MAX_BYTES:
            raise ExchangeError("package exceeds maximum size")
        if _digest(file) != expected:
            raise ExchangeError(f"source hash mismatch: {name}")
        recorded.append({"path": name, "sha256": expected, "size": size, "role": role})
    if not {"pool_spec", "source_manifest", "data"}.issubset(roles):
        raise ExchangeError("pool_spec, source_manifest and data are all mandatory")
    pools = [x for x in recorded if x["role"] == "pool_spec"]
    sources = [x for x in recorded if x["role"] == "source_manifest"]
    if len(pools) != 1 or pools[0]["path"] != POOLS[recipe["pool_id"]]:
        raise ExchangeError("exact governed selected-pool file must be pinned")
    if len(sources) != 1 or sources[0]["path"] != source_path or sources[0]["sha256"] != source_sha:
        raise ExchangeError("exact canonical source manifest must be pinned")
    return {
        "schema_version": VERSION,
        "kind": "private_research_input",
        "study_id": recipe["study_id"],
        "market": recipe["market"],
        "pool_id": recipe["pool_id"],
        "data_cutoff": recipe["data_cutoff"],
        "repo_revision": revision,
        "rights_class": recipe["rights_class"],
        "source_manifest_path": source_path,
        "source_manifest_sha256": source_sha,
        "pit_certified": False,
        "research_only": True,
        "trade_ready": False,
        "files": sorted(recorded, key=lambda item: item["path"]),
    }


def pack(repo_root: Path, recipe_path: Path, output_zip: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    manifest = _checked_recipe(recipe, root)
    if output_zip.resolve().is_relative_to(root):
        raise ExchangeError("private exchange archives must be written outside the public repository")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        # Exclusive creation: a pre-existing archive must never be deleted or replaced.
        if output_zip.exists():
            raise ExchangeError("archive already exists; immutable packages cannot be overwritten")
        with zipfile.ZipFile(output_zip, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as archive:
            created = True
            payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8") + b"\n"
            header = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            header.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(header, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            for entry in manifest["files"]:
                filename = entry["path"]
                info = zipfile.ZipInfo(f"files/{filename}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                with (root / filename).open("rb") as src, archive.open(info, "w") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
    except Exception:
        # Never delete an existing immutable archive after an exclusive-open failure.
        if created:
            output_zip.unlink(missing_ok=True)
        raise
    # Re-hash the completed archive to close the source-refresh race between
    # initial source checks and ZIP streaming; never return a bad package as ready.
    try:
        if verify(output_zip) != manifest:
            raise ExchangeError("archive manifest differs from frozen source")
    except Exception:
        output_zip.unlink(missing_ok=True)
        raise
    return {"package": str(output_zip), "sha256": _digest(output_zip), "manifest": manifest}


def verify(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) < 4 or len(infos) > MAX_FILES + 1:
            raise ExchangeError("unexpected archive member count")
        names = [x.filename for x in infos]
        if len(names) != len(set(names)) or names.count("manifest.json") != 1:
            raise ExchangeError("duplicate or missing manifest")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 1024 * 1024:
            raise ExchangeError("manifest too large")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != VERSION:
            raise ExchangeError("unsupported exchange archive")
        if manifest.get("kind") != "private_research_input" or (
            manifest.get("research_only") is not True or
            manifest.get("trade_ready") is not False or
            manifest.get("pit_certified") is not False or
            manifest.get("rights_class") != "private_cloud_research_allowed"
        ):
            raise ExchangeError("invalid research or rights boundary")
        if manifest.get("pool_id") not in POOLS or not COMMIT_RE.fullmatch(
            str(manifest.get("repo_revision", ""))
        ):
            raise ExchangeError("invalid identity or execution revision")
        market = manifest.get("market")
        if market not in {"us", "cn"} or ((market == "us") !=
                                          str(manifest["pool_id"]).startswith("us_")):
            raise ExchangeError("archive market/pool mismatch")
        if not isinstance(manifest.get("data_cutoff"), str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", manifest["data_cutoff"]
        ):
            raise ExchangeError("invalid archive data cutoff")
        entries = manifest.get("files")
        if not isinstance(entries, list) or len(entries) < 3 or len(entries) > MAX_FILES:
            raise ExchangeError("invalid archive entries")
        expected_names = {"manifest.json"}
        total_size = 0
        roles: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size", "role"}:
                raise ExchangeError("invalid file manifest entry")
            name = _safe_name(entry["path"])
            if entry["role"] not in {"pool_spec", "source_manifest", "data", "study_spec"}:
                raise ExchangeError("unexpected file role")
            sha = _sha(entry["sha256"], f"sha256:{name}")
            size = entry["size"]
            if not isinstance(size, int) or size < 0:
                raise ExchangeError("invalid file size")
            member_name = f"files/{name}"
            expected_names.add(member_name)
            member = archive.getinfo(member_name)
            if member.file_size != size or member.is_dir():
                raise ExchangeError(f"declared file size mismatch: {name}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ExchangeError("symlinked archive entries are not allowed")
            total_size += size
            if total_size > MAX_BYTES:
                raise ExchangeError("archive exceeds maximum declared bytes")
            h = hashlib.sha256()
            actual_size = 0
            with archive.open(member) as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
                    actual_size += len(block)
            if actual_size != size or h.hexdigest() != sha:
                raise ExchangeError(f"archive content mismatch: {name}")
            roles.add(entry["role"])
        if set(names) != expected_names or not {"pool_spec", "source_manifest", "data"}.issubset(roles):
            raise ExchangeError("missing or unexpected archive entries")
        source = [x for x in entries if x["role"] == "source_manifest"]
        pool = [x for x in entries if x["role"] == "pool_spec"]
        if (len(source) != 1 or source[0]["path"] != manifest.get("source_manifest_path")
                or source[0]["sha256"] != manifest.get("source_manifest_sha256")
                or len(pool) != 1 or pool[0]["path"] != POOLS[manifest["pool_id"]]):
            raise ExchangeError("source/pool authority mismatch")
    return manifest


def stage(archive_path: Path, checkout: Path) -> dict[str, Any]:
    """Import to an isolated pinned checkout; never replace differing existing files."""
    manifest = verify(archive_path)
    root = checkout.resolve()
    if not root.is_dir() or _git_head(root) != manifest["repo_revision"]:
        raise ExchangeError("stage target must be the exact pinned Git checkout")
    for entry in manifest["files"]:
        dest = _safe_target(root, entry["path"])
        if dest.exists() and (not dest.is_file() or dest.is_symlink()
                              or _digest(dest) != entry["sha256"]):
            raise ExchangeError(f"refusing to overwrite different checkout data: {entry['path']}")
    imported = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        for entry in manifest["files"]:
            dest = _safe_target(root, entry["path"])
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with dest.open("xb") as out:
                    created = True
                    with archive.open(f"files/{entry['path']}") as source:
                        shutil.copyfileobj(source, out, length=1024 * 1024)
                if _digest(dest) != entry["sha256"]:
                    raise ExchangeError(f"staged file mismatch: {entry['path']}")
            except Exception:
                if created:
                    dest.unlink(missing_ok=True)
                raise
            imported += 1
    return {"staged_new_files": imported, "study_id": manifest["study_id"],
            "repo_revision": manifest["repo_revision"], "research_only": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private research exchange (no cloud upload)")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("pack")
    create.add_argument("--repo-root", type=Path, required=True)
    create.add_argument("--recipe", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--archive", type=Path, required=True)
    restore = sub.add_parser("stage")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "pack":
            result = pack(args.repo_root, args.recipe, args.output)
        elif args.action == "verify":
            result = verify(args.archive)
        else:
            result = stage(args.archive, args.checkout)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except (ExchangeError, OSError, json.JSONDecodeError, zipfile.BadZipFile, KeyError) as exc:
        print(f"BLOCKED_EXCHANGE: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
