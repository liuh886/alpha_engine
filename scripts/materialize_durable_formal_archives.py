from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_MANIFEST_DIR = Path("data/research/formal_promotions")


class DurableArchiveError(ValueError):
    """Raised when a durable formal evidence archive is missing or inconsistent."""


def _safe_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise DurableArchiveError(f"unsafe repository archive path: {value!r}")
    return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableArchiveError(f"invalid promotion manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise DurableArchiveError(f"manifest root must be an object: {path}")
    return payload


def materialize(
    repository_root: Path,
    manifest_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifests = sorted((repository_root / manifest_dir).glob("*.json"))
    if not manifests:
        raise DurableArchiveError(f"no promotion manifests found: {manifest_dir}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    rows: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for manifest_path in manifests:
        payload = _read_manifest(manifest_path)
        model_id = str(payload.get("model_id") or "").strip()
        if not model_id or model_id in seen_models:
            raise DurableArchiveError(f"invalid or duplicate model_id: {manifest_path}")
        seen_models.add(model_id)

        source = payload.get("source")
        durability = payload.get("durability")
        if not isinstance(source, dict) or not isinstance(durability, dict):
            raise DurableArchiveError(f"source/durability missing: {manifest_path}")
        if durability.get("status") != "durable_repository_archive":
            raise DurableArchiveError(f"{model_id}: source is not durable")
        if durability.get("non_regenerable_after_expiry") is not False:
            raise DurableArchiveError(f"{model_id}: durable source remains expiry-blocked")

        relative = _safe_path(str(durability.get("approved_durable_location") or ""))
        source_path = repository_root / relative
        if not source_path.is_file():
            raise DurableArchiveError(f"{model_id}: durable archive missing: {relative}")

        expected_digest = str(source.get("artifact_digest") or "")
        if not expected_digest.startswith("sha256:"):
            raise DurableArchiveError(f"{model_id}: invalid source digest")
        observed_digest = "sha256:" + _sha256(source_path)
        if observed_digest != expected_digest:
            raise DurableArchiveError(
                f"{model_id}: durable archive digest mismatch: "
                f"expected {expected_digest}, found {observed_digest}"
            )

        destination = output_dir / f"{model_id}.zip"
        shutil.copyfile(source_path, destination)
        rows.append(
            {
                "model_id": model_id,
                "repository_path": relative,
                "archive_size": source_path.stat().st_size,
                "archive_digest": observed_digest,
                "original_workflow_run_id": source.get("workflow_run_id"),
                "original_artifact_id": source.get("artifact_id"),
                "original_artifact_expires_at": source.get("expires_at"),
            }
        )

    return {
        "schema_version": "1.0.0",
        "status": "materialized",
        "research_only": True,
        "trade_ready": False,
        "archives": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and materialize repository-retained formal source archives."
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    output_dir = repository_root / args.output_dir
    receipt_path = repository_root / args.receipt
    try:
        receipt = materialize(
            repository_root,
            args.manifest_dir,
            output_dir,
        )
    except DurableArchiveError as exc:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps({"status": "blocked", "error": str(exc)}, indent=2) + "\n",
            encoding="utf-8",
        )
        raise

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
