from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

BUNDLE_SCHEMA_VERSION = "1.0.0"
FRONTEND_READER_RANGE = ">=1.0.0 <2.0.0"
REQUIRED_PATHS = ("data/manifest.json", "data/models.json")


class BundleBuildError(ValueError):
    """Raised when a research bundle cannot be built without inference."""


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    path: str
    media_type: str
    byte_size: int
    sha256: str
    required: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BundleBuildError(f"unsafe artifact path: {path}")
    return candidate


def _kind_for(path: PurePosixPath) -> str:
    suffix = path.suffix.lower()
    if path.as_posix() == "data/models.json":
        return "model_index"
    if path.as_posix() == "data/manifest.json":
        return "static_export_manifest"
    if path.as_posix() == "data/model-data-readiness.json":
        return "data_readiness_index"
    if path.as_posix() == "data/data-components.json":
        return "data_component_index"
    if path.as_posix() == "data/training-profiles.json":
        return "training_readiness_index"
    if "curve" in path.parts or path.parent.name == "curves":
        return "backtest_series"
    if path.parts and path.parts[0] == "reports":
        return "report"
    if path.parts and path.parts[0] == "notebooks":
        return "notebook"
    if path.parts and path.parts[0] == "docs":
        return "methodology"
    if suffix in {".csv", ".jsonl", ".parquet"}:
        return "table"
    return "supporting_artifact"


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if path.suffix == ".ipynb":
        return "application/x-ipynb+json"
    if path.suffix == ".jsonl":
        return "application/x-ndjson"
    return guessed or "application/octet-stream"


class ResearchBundleBuilder:
    def __init__(self, source_root: Path, output_root: Path) -> None:
        self.source_root = source_root.resolve()
        self.output_root = output_root.resolve()
        if self.source_root == self.output_root or self.source_root in self.output_root.parents:
            raise BundleBuildError("output directory must not be inside source directory")

    def _validate_required(self) -> None:
        for relative in REQUIRED_PATHS:
            path = self.source_root / _safe_relative(relative)
            if not path.is_file():
                raise BundleBuildError(f"required artifact missing: {relative}")

    def _discover(self) -> list[PurePosixPath]:
        allowed_roots = ("data", "reports", "notebooks", "docs")
        paths: list[PurePosixPath] = []
        for root_name in allowed_roots:
            root = self.source_root / root_name
            if not root.exists():
                continue
            for item in root.rglob("*"):
                if item.is_file():
                    paths.append(PurePosixPath(item.relative_to(self.source_root).as_posix()))
        return sorted(paths, key=lambda item: item.as_posix())

    def build(self, *, title: str = "Alpha Engine Research Bundle") -> dict[str, Any]:
        self._validate_required()
        discovered = self._discover()
        if self.output_root.exists():
            shutil.rmtree(self.output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

        records: list[ArtifactRecord] = []
        for relative in discovered:
            safe = _safe_relative(relative.as_posix())
            source = self.source_root / safe
            destination = self.output_root / safe
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            records.append(
                ArtifactRecord(
                    artifact_id=hashlib.sha256(safe.as_posix().encode("utf-8")).hexdigest()[:16],
                    kind=_kind_for(safe),
                    path=safe.as_posix(),
                    media_type=_media_type(source),
                    byte_size=source.stat().st_size,
                    sha256=_sha256(source),
                    required=safe.as_posix() in REQUIRED_PATHS,
                )
            )

        static_manifest = json.loads(
            (self.source_root / "data/manifest.json").read_text(encoding="utf-8")
        )
        models = json.loads((self.source_root / "data/models.json").read_text(encoding="utf-8"))
        generated_at = static_manifest.get("generated_at") or datetime.now(timezone.utc).isoformat()
        bundle_id_seed = "\n".join(f"{record.path}:{record.sha256}" for record in records)
        bundle_id = hashlib.sha256(bundle_id_seed.encode("utf-8")).hexdigest()

        markets = sorted(
            {str(row.get("market", "unknown")).lower() for row in models if isinstance(row, dict)}
        )
        manifest: dict[str, Any] = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "frontend_reader_range": FRONTEND_READER_RANGE,
            "bundle_id": bundle_id,
            "title": title,
            "generated_at": generated_at,
            "evidence_cutoff": static_manifest.get("evidence_cutoff"),
            "research_only": True,
            "trade_ready": False,
            "scope": {
                "markets": markets,
                "snapshot_id": static_manifest.get("snapshot_id"),
                "model_count": len(models),
            },
            "warnings": list(static_manifest.get("warnings", [])),
            "blocked_gates": list(static_manifest.get("blocked_gates", [])),
            "promotion_decision": static_manifest.get("promotion_decision", "not_declared"),
            "artifacts": [asdict(record) for record in records],
        }
        readiness_path = self.source_root / "data/model-data-readiness.json"
        if readiness_path.is_file():
            readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
            if not isinstance(readiness, dict):
                raise BundleBuildError("model-data-readiness.json must be a mapping")
            manifest["data_readiness"] = {
                "bundle_id": readiness.get("bundle_id"),
                "evidence_cutoff": readiness.get("evidence_cutoff"),
                "summary": readiness.get("summary", {}),
            }
        manifest_path = self.output_root / "alpha-engine-bundle.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest


def build_research_bundle(
    source_root: Path,
    output_root: Path,
    *,
    title: str = "Alpha Engine Research Bundle",
) -> dict[str, Any]:
    return ResearchBundleBuilder(source_root, output_root).build(title=title)


def verify_bundle(bundle_root: Path) -> list[str]:
    manifest_path = bundle_root / "alpha-engine-bundle.json"
    if not manifest_path.is_file():
        raise BundleBuildError("alpha-engine-bundle.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(manifest.get("schema_version", "")).split(".")[0] != "1":
        raise BundleBuildError("unsupported bundle major version")
    verified: list[str] = []
    for item in manifest.get("artifacts", []):
        relative = _safe_relative(str(item["path"]))
        path = bundle_root / relative
        if not path.is_file():
            raise BundleBuildError(f"bundle artifact missing: {relative}")
        if _sha256(path) != item.get("sha256"):
            raise BundleBuildError(f"bundle artifact hash mismatch: {relative}")
        verified.append(relative.as_posix())
    return verified


def artifact_paths(manifest: dict[str, Any], kinds: Iterable[str]) -> list[str]:
    wanted = set(kinds)
    return [
        str(item["path"]) for item in manifest.get("artifacts", []) if item.get("kind") in wanted
    ]
