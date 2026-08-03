from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

DEFAULT_MANIFEST_DIR = Path("data/research/formal_promotions")
DEFAULT_COMMITTED_DIR = Path("data/research/formal_backtests")
DEFAULT_BUILDER = Path("scripts/build_formal_model_backtests.py")
GITHUB_ACCEPT = "application/vnd.github+json"


class FormalPromotionError(ValueError):
    """Raised when a formal baseline cannot be reproduced from immutable evidence."""


@dataclass(frozen=True)
class ArtifactSource:
    repository: str
    workflow_run_id: int
    workflow_head_sha: str
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    expires_at: str
    materialize_under: str
    required_paths: tuple[str, ...]


@dataclass(frozen=True)
class PromotionManifest:
    path: Path
    model_id: str
    package_path: str
    evidence_cutoff: str
    source: ArtifactSource
    durability_status: str
    on_expiry: str


def _safe_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise FormalPromotionError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalPromotionError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalPromotionError(f"JSON root must be an object: {path}")
    return payload


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FormalPromotionError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise FormalPromotionError(f"timestamp must be timezone-aware: {value}")
    return parsed.astimezone(timezone.utc)


def load_manifest(path: Path) -> PromotionManifest:
    payload = _json_object(path)
    if str(payload.get("schema_version", "")).split(".")[0] != "1":
        raise FormalPromotionError(f"unsupported promotion manifest schema: {path}")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise FormalPromotionError(f"promotion manifest weakens research boundary: {path}")

    model_id = str(payload.get("model_id") or "").strip()
    package_path = _safe_path(str(payload.get("package_path") or ""))
    evidence_cutoff = str(payload.get("evidence_cutoff") or "").strip()
    if not model_id or not evidence_cutoff:
        raise FormalPromotionError(f"model_id/evidence_cutoff missing: {path}")

    source_payload = payload.get("source")
    if not isinstance(source_payload, dict):
        raise FormalPromotionError(f"source identity missing: {path}")
    if source_payload.get("kind") != "github_actions_artifact":
        raise FormalPromotionError(f"unsupported source kind: {path}")

    digest = str(source_payload.get("artifact_digest") or "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise FormalPromotionError(f"invalid artifact digest: {path}")
    head_sha = str(source_payload.get("workflow_head_sha") or "")
    if len(head_sha) != 40 or any(char not in "0123456789abcdef" for char in head_sha):
        raise FormalPromotionError(f"invalid workflow head SHA: {path}")

    layout = source_payload.get("source_layout")
    if not isinstance(layout, dict):
        raise FormalPromotionError(f"source layout missing: {path}")
    required = layout.get("required_paths")
    if not isinstance(required, list) or not required:
        raise FormalPromotionError(f"required source paths missing: {path}")

    durability = payload.get("durability")
    if not isinstance(durability, dict):
        raise FormalPromotionError(f"durability declaration missing: {path}")
    durability_status = str(durability.get("status") or "")
    on_expiry = str(durability.get("on_expiry") or "")
    allowed = {"durable_repository_archive", "time_bounded_actions_artifact"}
    if durability_status not in allowed:
        raise FormalPromotionError(f"unsupported durability status: {path}")
    if (
        durability_status == "time_bounded_actions_artifact"
        and on_expiry != "block_non_regenerable"
    ):
        raise FormalPromotionError(f"time-bounded source must block after expiry: {path}")

    try:
        workflow_run_id = int(source_payload["workflow_run_id"])
        artifact_id = int(source_payload["artifact_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalPromotionError(f"invalid workflow/artifact identity: {path}") from exc

    source = ArtifactSource(
        repository=str(source_payload.get("repository") or ""),
        workflow_run_id=workflow_run_id,
        workflow_head_sha=head_sha,
        artifact_id=artifact_id,
        artifact_name=str(source_payload.get("artifact_name") or ""),
        artifact_digest=digest,
        expires_at=str(source_payload.get("expires_at") or ""),
        materialize_under=_safe_path(str(layout.get("materialize_under") or "")),
        required_paths=tuple(_safe_path(str(item)) for item in required),
    )
    if not source.repository or not source.artifact_name:
        raise FormalPromotionError(f"incomplete artifact identity: {path}")
    _parse_time(source.expires_at)

    expected_package = f"data/research/formal_backtests/{model_id}.json"
    if package_path != expected_package:
        raise FormalPromotionError(
            f"package path/model mismatch: expected {expected_package}, found {package_path}"
        )
    return PromotionManifest(
        path=path,
        model_id=model_id,
        package_path=package_path,
        evidence_cutoff=evidence_cutoff,
        source=source,
        durability_status=durability_status,
        on_expiry=on_expiry,
    )


def load_manifests(directory: Path) -> tuple[PromotionManifest, ...]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise FormalPromotionError(f"no promotion manifests found: {directory}")
    manifests = tuple(load_manifest(path) for path in paths)
    ids = [manifest.model_id for manifest in manifests]
    if len(ids) != len(set(ids)):
        raise FormalPromotionError("duplicate model_id in promotion manifests")
    destinations = [manifest.source.materialize_under for manifest in manifests]
    if len(destinations) != len(set(destinations)):
        raise FormalPromotionError("duplicate source materialization destination")
    return manifests


def validate_artifact_metadata(
    manifest: PromotionManifest,
    metadata: dict[str, Any],
    *,
    now: datetime,
) -> None:
    source = manifest.source
    if int(metadata.get("id", -1)) != source.artifact_id:
        raise FormalPromotionError(f"{manifest.model_id}: artifact ID mismatch")
    if metadata.get("name") != source.artifact_name:
        raise FormalPromotionError(f"{manifest.model_id}: artifact name mismatch")
    if metadata.get("digest") != source.artifact_digest:
        raise FormalPromotionError(f"{manifest.model_id}: artifact digest mismatch")
    if metadata.get("expired") is True:
        raise FormalPromotionError(
            f"{manifest.model_id}: source artifact is expired and non-regenerable"
        )
    if metadata.get("expires_at") != source.expires_at:
        raise FormalPromotionError(f"{manifest.model_id}: artifact expiry mismatch")
    workflow = metadata.get("workflow_run")
    if not isinstance(workflow, dict):
        raise FormalPromotionError(f"{manifest.model_id}: workflow identity missing")
    if int(workflow.get("id", -1)) != source.workflow_run_id:
        raise FormalPromotionError(f"{manifest.model_id}: workflow run mismatch")
    if workflow.get("head_sha") != source.workflow_head_sha:
        raise FormalPromotionError(f"{manifest.model_id}: workflow head SHA mismatch")
    if now >= _parse_time(source.expires_at):
        raise FormalPromotionError(
            f"{manifest.model_id}: declared source expired at {source.expires_at}; "
            "promotion is blocked rather than rebuilt from newer evidence"
        )


def _request(url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": GITHUB_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": "alpha-engine-formal-promotion/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def fetch_sources(
    manifests: Iterable[PromotionManifest],
    *,
    archive_dir: Path,
    token: str,
    now: datetime,
) -> list[dict[str, Any]]:
    if not token:
        raise FormalPromotionError("GITHUB_TOKEN is required to fetch immutable artifacts")
    archive_dir.mkdir(parents=True, exist_ok=True)
    fetched: list[dict[str, Any]] = []
    for manifest in manifests:
        source = manifest.source
        api_root = (
            f"https://api.github.com/repos/{source.repository}/actions/artifacts/"
            f"{source.artifact_id}"
        )
        try:
            with urllib.request.urlopen(_request(api_root, token), timeout=30) as response:
                metadata = json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise FormalPromotionError(
                f"{manifest.model_id}: unable to read artifact metadata"
            ) from exc
        if not isinstance(metadata, dict):
            raise FormalPromotionError(f"{manifest.model_id}: invalid artifact metadata")
        validate_artifact_metadata(manifest, metadata, now=now)

        archive = archive_dir / f"{manifest.model_id}.zip"
        try:
            with urllib.request.urlopen(
                _request(f"{api_root}/zip", token), timeout=120
            ) as response, archive.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        except (OSError, urllib.error.URLError) as exc:
            raise FormalPromotionError(
                f"{manifest.model_id}: unable to download immutable artifact"
            ) from exc
        observed = "sha256:" + _sha256_file(archive)
        if observed != source.artifact_digest:
            archive.unlink(missing_ok=True)
            raise FormalPromotionError(
                f"{manifest.model_id}: downloaded archive digest mismatch"
            )
        fetched.append(
            {
                "model_id": manifest.model_id,
                "workflow_run_id": source.workflow_run_id,
                "workflow_head_sha": source.workflow_head_sha,
                "artifact_id": source.artifact_id,
                "artifact_digest": observed,
                "expires_at": source.expires_at,
                "archive": archive.as_posix(),
            }
        )
    return fetched


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise FormalPromotionError(f"unsafe archive member: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise FormalPromotionError(
                    f"archive symlink is not allowed: {info.filename}"
                )
            resolved = destination.joinpath(*relative.parts).resolve()
            if resolved != destination_root and destination_root not in resolved.parents:
                raise FormalPromotionError(
                    f"archive member escapes destination: {info.filename}"
                )
        bundle.extractall(destination)


def materialize_sources(
    manifests: Iterable[PromotionManifest],
    *,
    archive_dir: Path,
    source_root: Path,
) -> None:
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True)
    for manifest in manifests:
        archive = archive_dir / f"{manifest.model_id}.zip"
        if not archive.is_file():
            raise FormalPromotionError(f"source archive missing: {archive}")
        observed = "sha256:" + _sha256_file(archive)
        if observed != manifest.source.artifact_digest:
            raise FormalPromotionError(
                f"{manifest.model_id}: local source archive digest mismatch"
            )
        destination = source_root / manifest.source.materialize_under
        _safe_extract(archive, destination)
        for required in manifest.source.required_paths:
            if not (destination / required).is_file():
                raise FormalPromotionError(
                    f"{manifest.model_id}: required source file missing: {required}"
                )


def _validate_package(manifest: PromotionManifest, package: dict[str, Any]) -> None:
    if package.get("model_id") != manifest.model_id:
        raise FormalPromotionError(
            f"{manifest.model_id}: generated package identity mismatch"
        )
    if package.get("record_type") != "formal_model_backtest":
        raise FormalPromotionError(f"{manifest.model_id}: invalid record type")
    if package.get("publication_status") != "accepted_formal_baseline":
        raise FormalPromotionError(f"{manifest.model_id}: invalid publication status")
    if package.get("research_only") is not True or package.get("trade_ready") is not False:
        raise FormalPromotionError(f"{manifest.model_id}: research boundary mismatch")
    if package.get("evidence_cutoff") != manifest.evidence_cutoff:
        raise FormalPromotionError(f"{manifest.model_id}: evidence cutoff mismatch")
    completeness = package.get("evidence_completeness")
    if not isinstance(completeness, dict) or completeness.get("status") not in {
        "complete",
        "partial",
    }:
        raise FormalPromotionError(
            f"{manifest.model_id}: evidence completeness is not explicitly declared"
        )
    if completeness.get("status") == "partial" and not isinstance(
        completeness.get("missing"), list
    ):
        raise FormalPromotionError(
            f"{manifest.model_id}: partial evidence must declare missing components"
        )
    evidence = package.get("evidence")
    if not isinstance(evidence, dict):
        raise FormalPromotionError(f"{manifest.model_id}: evidence identity missing")
    if int(evidence.get("workflow_run_id", -1)) != manifest.source.workflow_run_id:
        raise FormalPromotionError(
            f"{manifest.model_id}: package workflow identity mismatch"
        )
    if int(evidence.get("artifact_id", -1)) != manifest.source.artifact_id:
        raise FormalPromotionError(
            f"{manifest.model_id}: package artifact identity mismatch"
        )
    if evidence.get("artifact_digest") != manifest.source.artifact_digest:
        raise FormalPromotionError(
            f"{manifest.model_id}: package artifact digest mismatch"
        )


def _pretty_json_bytes(payload: bytes) -> list[str]:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8", errors="replace").splitlines()
    return json.dumps(decoded, indent=2, sort_keys=True).splitlines()


def _diff(label: str, expected: bytes, actual: bytes) -> str:
    lines = difflib.unified_diff(
        _pretty_json_bytes(expected),
        _pretty_json_bytes(actual),
        fromfile=f"committed/{label}",
        tofile=f"generated/{label}",
        lineterm="",
    )
    return "\n".join(list(lines)[:400])


def verify_reproduction(
    manifests: tuple[PromotionManifest, ...],
    *,
    repository_root: Path,
    archive_dir: Path,
    source_root: Path,
    generated_dir: Path,
    committed_dir: Path,
    builder: Path,
    receipt_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    materialize_sources(manifests, archive_dir=archive_dir, source_root=source_root)
    if generated_dir.exists():
        shutil.rmtree(generated_dir)
    generated_dir.mkdir(parents=True)
    try:
        subprocess.run(
            [
                sys.executable,
                str(repository_root / builder),
                "--source-root",
                str(source_root),
                "--output-dir",
                str(generated_dir),
            ],
            cwd=repository_root,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FormalPromotionError("deterministic formal package builder failed") from exc

    generated_catalog_bytes = (generated_dir / "catalog.json").read_bytes()
    committed_catalog_bytes = (committed_dir / "catalog.json").read_bytes()
    generated_catalog = json.loads(generated_catalog_bytes)
    committed_catalog = json.loads(committed_catalog_bytes)
    if not isinstance(generated_catalog, dict) or not isinstance(committed_catalog, dict):
        raise FormalPromotionError("formal catalog must be a JSON object")

    generated_records = {
        str(record["model_id"]): record
        for record in generated_catalog.get("records", [])
        if isinstance(record, dict)
    }
    committed_records = {
        str(record["model_id"]): record
        for record in committed_catalog.get("records", [])
        if isinstance(record, dict)
    }
    expected_ids = {manifest.model_id for manifest in manifests}
    if set(generated_records) != expected_ids or set(committed_records) != expected_ids:
        raise FormalPromotionError("formal catalog/model manifest allow-list mismatch")

    results: list[dict[str, Any]] = []
    diffs: list[str] = []
    for manifest in manifests:
        generated_path = generated_dir / f"{manifest.model_id}.json"
        committed_path = repository_root / manifest.package_path
        generated_bytes = generated_path.read_bytes()
        committed_bytes = committed_path.read_bytes()
        generated_package = json.loads(generated_bytes)
        committed_package = json.loads(committed_bytes)
        if not isinstance(generated_package, dict) or not isinstance(committed_package, dict):
            raise FormalPromotionError(
                f"{manifest.model_id}: package must be a JSON object"
            )
        _validate_package(manifest, generated_package)
        _validate_package(manifest, committed_package)

        generated_hash = _sha256_bytes(generated_bytes)
        committed_hash = _sha256_bytes(committed_bytes)
        if generated_records[manifest.model_id].get("sha256") != generated_hash:
            raise FormalPromotionError(
                f"{manifest.model_id}: generated catalog hash mismatch"
            )
        if committed_records[manifest.model_id].get("sha256") != committed_hash:
            raise FormalPromotionError(
                f"{manifest.model_id}: committed catalog hash mismatch"
            )
        byte_exact = generated_bytes == committed_bytes
        if not byte_exact:
            diffs.append(
                _diff(f"{manifest.model_id}.json", committed_bytes, generated_bytes)
            )
        results.append(
            {
                "model_id": manifest.model_id,
                "source_artifact_id": manifest.source.artifact_id,
                "source_digest": manifest.source.artifact_digest,
                "evidence_cutoff": manifest.evidence_cutoff,
                "generated_sha256": generated_hash,
                "committed_sha256": committed_hash,
                "byte_exact": byte_exact,
            }
        )

    catalog_exact = generated_catalog_bytes == committed_catalog_bytes
    if not catalog_exact:
        diffs.append(_diff("catalog.json", committed_catalog_bytes, generated_catalog_bytes))
    status = (
        "verified"
        if catalog_exact and all(row["byte_exact"] for row in results)
        else "mismatch"
    )
    receipt = {
        "schema_version": "1.0.0",
        "status": status,
        "generator": builder.as_posix(),
        "generator_sha256": _sha256_file(repository_root / builder),
        "research_only": True,
        "trade_ready": False,
        "catalog_byte_exact": catalog_exact,
        "models": results,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    table = [
        "# Formal baseline promotion verification",
        "",
        f"Status: **{status}**",
        "",
        "| Model | Source artifact | Evidence cutoff | Byte exact |",
        "|---|---:|---|---|",
    ]
    for row in results:
        table.append(
            f"| `{row['model_id']}` | `{row['source_artifact_id']}` | "
            f"`{row['evidence_cutoff']}` | `{str(row['byte_exact']).lower()}` |"
        )
    table.extend(
        [
            "",
            f"Catalog byte exact: `{str(catalog_exact).lower()}`",
            "",
            "No files are edited or promoted by this verification workflow.",
        ]
    )
    if diffs:
        table.extend(["", "## Differences", "", "```diff", "\n\n".join(diffs), "```"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(table) + "\n", encoding="utf-8")
    if status != "verified":
        raise FormalPromotionError(
            "generated formal packages differ from the proposed committed bytes"
        )
    return receipt


def _now(value: str | None) -> datetime:
    return _parse_time(value) if value else datetime.now(timezone.utc)


def _write_status(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and byte-verify formal baselines from immutable evidence."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    fetch_parser.add_argument("--archive-dir", type=Path, required=True)
    fetch_parser.add_argument("--now")
    fetch_parser.add_argument("--receipt", type=Path)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    verify_parser.add_argument("--archive-dir", type=Path, required=True)
    verify_parser.add_argument("--source-root", type=Path, required=True)
    verify_parser.add_argument("--generated-dir", type=Path, required=True)
    verify_parser.add_argument("--committed-dir", type=Path, default=DEFAULT_COMMITTED_DIR)
    verify_parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--summary", type=Path, required=True)

    args = parser.parse_args()
    repository_root = Path(".").resolve()
    receipt_path = repository_root / args.receipt if args.receipt else None
    try:
        manifests = load_manifests(repository_root / args.manifest_dir)
        if args.command == "fetch":
            fetched = fetch_sources(
                manifests,
                archive_dir=repository_root / args.archive_dir,
                token=os.environ.get("GITHUB_TOKEN", ""),
                now=_now(args.now),
            )
            payload = {"status": "fetched", "sources": fetched}
            _write_status(receipt_path, payload)
            print(json.dumps(payload, sort_keys=True))
            return

        receipt = verify_reproduction(
            manifests,
            repository_root=repository_root,
            archive_dir=repository_root / args.archive_dir,
            source_root=repository_root / args.source_root,
            generated_dir=repository_root / args.generated_dir,
            committed_dir=repository_root / args.committed_dir,
            builder=args.builder,
            receipt_path=repository_root / args.receipt,
            summary_path=repository_root / args.summary,
        )
        print(json.dumps(receipt, sort_keys=True))
    except FormalPromotionError as exc:
        _write_status(receipt_path, {"status": "blocked", "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
