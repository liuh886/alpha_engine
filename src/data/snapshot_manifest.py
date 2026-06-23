"""Manifest contract for immutable, content-addressed data snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SnapshotManifest:
    """Point-in-time descriptor of exact provider bytes and their policies."""

    snapshot_id: str = ""
    identity_version: int = 2
    content_hash: str = ""
    file_checksums: dict[str, str] = field(default_factory=dict)
    source_adapter: str = ""
    source_policy: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1"
    universe: Any = ""
    calendar: dict[str, Any] = field(default_factory=dict)
    date_range: dict[str, str] = field(default_factory=dict)
    frequency: str = "day"
    adjustment_policy: dict[str, Any] = field(default_factory=dict)
    quality_policy: dict[str, Any] = field(default_factory=dict)
    quality_report: dict[str, Any] = field(default_factory=dict)
    update_summary: dict[str, Any] = field(default_factory=dict)
    quality_verdict: str = "pass"
    storage_uri: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)

    def identity_payload(self) -> dict:
        """Return only immutable identity fields, excluding location and time."""
        payload = self.to_dict()
        payload.pop("snapshot_id", None)
        payload.pop("storage_uri", None)
        payload.pop("created_at", None)
        return payload

    def computed_snapshot_id(self) -> str:
        encoded = json.dumps(
            self.identity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> SnapshotManifest:
        return cls(
            snapshot_id=d.get("snapshot_id", ""),
            identity_version=int(d.get("identity_version", 1)),
            content_hash=d.get("content_hash", ""),
            file_checksums=d.get("file_checksums") or {},
            source_adapter=d.get("source_adapter", ""),
            source_policy=d.get("source_policy") or {},
            schema_version=d.get("schema_version", "1"),
            universe=d.get("universe", ""),
            calendar=d.get("calendar") or {},
            date_range=d.get("date_range") or {},
            frequency=d.get("frequency", "day"),
            adjustment_policy=d.get("adjustment_policy") or {},
            quality_policy=d.get("quality_policy") or {},
            quality_report=d.get("quality_report") or {},
            update_summary=d.get("update_summary") or {},
            quality_verdict=d.get("quality_verdict", "unknown"),
            storage_uri=d.get("storage_uri", ""),
            created_at=d.get("created_at", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> SnapshotManifest:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("snapshot manifest must be a JSON object")
        return cls.from_dict(payload)

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> SnapshotManifest:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
