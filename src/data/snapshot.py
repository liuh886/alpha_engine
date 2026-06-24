"""Immutable, content-addressed Qlib provider snapshots."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from src.data.snapshot_manifest import SnapshotManifest

_MANIFEST_NAME = "manifest.json"
_LATEST_NAME = "latest"
_SNAPSHOTS_DIR = "snapshots"


def _hash_file(path: Path, *, chunk_size: int = 65_536) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compute_aggregate_hash(file_checksums: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative_path in sorted(file_checksums):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_checksums[relative_path].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _list_data_files(data_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(data_dir.rglob("*"))
        if path.is_file() and not path.name.startswith(".") and path.name != _MANIFEST_NAME
    ]


def _checksums(data_dir: Path, files: list[Path]) -> dict[str, str]:
    return {
        path.relative_to(data_dir).as_posix(): _hash_file(path)
        for path in files
    }


class DataSnapshot:
    """A verified, immutable provider directory and its exact manifest."""

    def __init__(self, snapshot_id: str, manifest: SnapshotManifest, store: Path):
        self._snapshot_id = snapshot_id
        self._manifest = manifest
        self._store = store

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id

    @property
    def manifest(self) -> SnapshotManifest:
        return self._manifest

    @property
    def provider_path(self) -> Path:
        return self._store / _SNAPSHOTS_DIR / self._snapshot_id

    @classmethod
    def create_snapshot(
        cls,
        data_dir: str | Path,
        *,
        store: str | Path | None = None,
        source_adapter: str = "",
        source_policy: dict[str, Any] | None = None,
        schema_version: str = "1",
        universe: Any = "",
        calendar: dict[str, Any] | None = None,
        date_range: dict[str, str] | None = None,
        frequency: str = "day",
        adjustment_policy: dict[str, Any] | None = None,
        quality_policy: dict[str, Any] | None = None,
        quality_report: dict[str, Any] | None = None,
        update_summary: dict[str, Any] | None = None,
        quality_verdict: str = "pass",
    ) -> DataSnapshot:
        from src.common.paths import SNAPSHOT_STORE

        data_dir = Path(data_dir).resolve()
        if not data_dir.is_dir():
            raise FileNotFoundError(f"data_dir not found: {data_dir}")

        data_files = _list_data_files(data_dir)
        if not data_files:
            raise ValueError(f"empty snapshot is not allowed: {data_dir}")

        file_checksums = _checksums(data_dir, data_files)
        content_hash = _compute_aggregate_hash(file_checksums)
        store = Path(store if store is not None else SNAPSHOT_STORE).resolve()
        provisional = SnapshotManifest(
            content_hash=content_hash,
            file_checksums=file_checksums,
            source_adapter=str(source_adapter),
            source_policy=source_policy or {},
            schema_version=str(schema_version),
            universe=universe,
            calendar=calendar or {},
            date_range=date_range or {},
            frequency=str(frequency),
            adjustment_policy=adjustment_policy or {},
            quality_policy=quality_policy or {},
            quality_report=quality_report or {},
            update_summary=update_summary or {},
            quality_verdict=str(quality_verdict),
        )
        snapshot_id = provisional.computed_snapshot_id()
        snapshot_dir = store / _SNAPSHOTS_DIR / snapshot_id
        manifest = SnapshotManifest.from_dict(
            {
                **provisional.to_dict(),
                "snapshot_id": snapshot_id,
                "storage_uri": str(snapshot_dir),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )

        if snapshot_dir.exists():
            return cls.resolve_snapshot(snapshot_id, store=store)

        snapshots_dir = store / _SNAPSHOTS_DIR
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        stage_dir = snapshots_dir / f".stage-{snapshot_id}-{uuid.uuid4().hex}"
        try:
            for source in data_files:
                destination = stage_dir / source.relative_to(data_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            manifest.write(stage_dir / _MANIFEST_NAME)
            cls._verify_directory(stage_dir, snapshot_id, manifest)
            os.replace(stage_dir, snapshot_dir)
        finally:
            if stage_dir.exists():
                shutil.rmtree(stage_dir)

        return cls.resolve_snapshot(snapshot_id, store=store)

    @classmethod
    def _verify_directory(
        cls, snapshot_dir: Path, requested_id: str, manifest: SnapshotManifest
    ) -> None:
        if manifest.snapshot_id != requested_id:
            raise ValueError(
                f"manifest identity mismatch: requested={requested_id} manifest={manifest.snapshot_id}"
            )
        computed_id = manifest.computed_snapshot_id()
        if computed_id != requested_id:
            raise ValueError(
                f"manifest identity mismatch: requested={requested_id} computed={computed_id}"
            )
        if not manifest.file_checksums:
            raise ValueError("empty snapshot manifest is not allowed")
        aggregate = _compute_aggregate_hash(manifest.file_checksums)
        if aggregate != manifest.content_hash:
            raise ValueError("manifest content hash mismatch")

        actual_files = _list_data_files(snapshot_dir)
        actual_paths = {path.relative_to(snapshot_dir).as_posix() for path in actual_files}
        expected_paths = set(manifest.file_checksums)
        if actual_paths != expected_paths:
            missing = sorted(expected_paths - actual_paths)
            extra = sorted(actual_paths - expected_paths)
            raise ValueError(f"snapshot file set mismatch: missing={missing} extra={extra}")
        for relative_path, expected in manifest.file_checksums.items():
            actual = _hash_file(snapshot_dir / relative_path)
            if actual != expected:
                raise ValueError(
                    f"checksum mismatch for {relative_path}: expected={expected} actual={actual}"
                )

    @classmethod
    def resolve_snapshot(
        cls, snapshot_id: str, *, store: str | Path | None = None
    ) -> DataSnapshot:
        from src.common.paths import SNAPSHOT_STORE

        snapshot_id = str(snapshot_id or "").strip()
        store = Path(store if store is not None else SNAPSHOT_STORE).resolve()
        snapshot_dir = store / _SNAPSHOTS_DIR / snapshot_id
        manifest_path = snapshot_dir / _MANIFEST_NAME
        if not manifest_path.exists():
            raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
        manifest = SnapshotManifest.read(manifest_path)
        cls._verify_directory(snapshot_dir, snapshot_id, manifest)
        return cls(snapshot_id=snapshot_id, manifest=manifest, store=store)

    @classmethod
    def publish_snapshot(
        cls, snapshot_id: str, *, store: str | Path | None = None
    ) -> None:
        from src.common.paths import SNAPSHOT_STORE

        store = Path(store if store is not None else SNAPSHOT_STORE).resolve()
        snapshot = cls.resolve_snapshot(snapshot_id, store=store)
        if snapshot.manifest.quality_verdict != "pass":
            raise ValueError(
                f"Cannot publish snapshot {snapshot_id}: "
                f"quality_verdict={snapshot.manifest.quality_verdict!r}"
            )
        store.mkdir(parents=True, exist_ok=True)
        latest_path = store / _LATEST_NAME
        temp_path = store / f".{_LATEST_NAME}.{uuid.uuid4().hex}.tmp"
        temp_path.write_text(snapshot_id, encoding="utf-8")
        os.replace(temp_path, latest_path)

    @classmethod
    def get_latest_snapshot(
        cls, *, store: str | Path | None = None
    ) -> DataSnapshot | None:
        from src.common.paths import SNAPSHOT_STORE

        store = Path(store if store is not None else SNAPSHOT_STORE).resolve()
        latest_path = store / _LATEST_NAME
        if not latest_path.exists():
            return None
        snapshot_id = latest_path.read_text(encoding="utf-8").strip()
        if not snapshot_id:
            return None
        return cls.resolve_snapshot(snapshot_id, store=store)

    def file_path(self, relative: str) -> Path:
        return self.provider_path / relative

    def list_files(self) -> list[str]:
        return sorted(self._manifest.file_checksums)

    def __repr__(self) -> str:
        return f"DataSnapshot(id={self._snapshot_id!r}, files={len(self._manifest.file_checksums)})"
