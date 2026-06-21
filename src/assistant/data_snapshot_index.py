from __future__ import annotations

import json
import time
from typing import Any

from src.assistant.base_index import BaseIndex
from src.data.snapshot_manifest import SnapshotManifest


class DataSnapshotIndex(BaseIndex):
    """SQLite index for exact manifests, with isolated legacy-marker support."""

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    dataset_key TEXT,
                    provider_uri TEXT,
                    freq TEXT,
                    latest_calendar_day TEXT,
                    generated_at TEXT,
                    payload_json TEXT,
                    created_at REAL,
                    manifest_json TEXT,
                    identity_version INTEGER NOT NULL DEFAULT 0,
                    authoritative INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(data_snapshots)").fetchall()
            }
            additions = {
                "manifest_json": "TEXT",
                "identity_version": "INTEGER NOT NULL DEFAULT 0",
                "authoritative": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE data_snapshots ADD COLUMN {name} {declaration}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_snapshots_dataset_freq "
                "ON data_snapshots(dataset_key, freq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_snapshots_latest_day "
                "ON data_snapshots(latest_calendar_day)"
            )

    def upsert_manifest(
        self, manifest: SnapshotManifest | dict[str, Any], *, dataset_key: str
    ) -> None:
        if isinstance(manifest, dict):
            manifest = SnapshotManifest.from_dict(manifest)
        if not isinstance(manifest, SnapshotManifest):
            raise ValueError("manifest must be a SnapshotManifest or dict")
        if manifest.identity_version < 2:
            raise ValueError("legacy snapshot identities are not authoritative")
        if not manifest.file_checksums:
            raise ValueError("authoritative manifest must contain file checksums")
        if manifest.computed_snapshot_id() != manifest.snapshot_id:
            raise ValueError("manifest identity mismatch")
        dataset_key = str(dataset_key or "").strip()
        if not dataset_key:
            raise ValueError("dataset_key is required")

        latest_day = str(
            manifest.calendar.get("latest_day") or manifest.date_range.get("end") or ""
        )
        manifest_payload = manifest.to_dict()
        self._write_row(
            snapshot_id=manifest.snapshot_id,
            dataset_key=dataset_key,
            provider_uri=manifest.storage_uri,
            freq=manifest.frequency,
            latest_calendar_day=latest_day,
            generated_at=manifest.created_at,
            payload={"dataset_key": dataset_key, "manifest": manifest_payload},
            manifest=manifest_payload,
            identity_version=manifest.identity_version,
            authoritative=1,
        )

    def upsert_legacy_marker(self, payload: dict) -> None:
        """Compatibility adapter for date-only markers; never authoritative."""
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise ValueError("payload.snapshot_id is required")
        self._write_row(
            snapshot_id=snapshot_id,
            dataset_key=str(payload.get("dataset_key") or ""),
            provider_uri=str(payload.get("provider_uri") or ""),
            freq=str(payload.get("freq") or ""),
            latest_calendar_day=str(payload.get("latest_calendar_day") or ""),
            generated_at=str(payload.get("generated_at") or ""),
            payload=payload,
            manifest=None,
            identity_version=0,
            authoritative=0,
        )

    def upsert(self, payload: dict) -> None:
        """Deprecated compatibility entry point for legacy marker callers."""
        self.upsert_legacy_marker(payload)

    def _write_row(
        self,
        *,
        snapshot_id: str,
        dataset_key: str,
        provider_uri: str,
        freq: str,
        latest_calendar_day: str,
        generated_at: str,
        payload: dict,
        manifest: dict | None,
        identity_version: int,
        authoritative: int,
    ) -> None:
        created_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO data_snapshots (
                    snapshot_id, dataset_key, provider_uri, freq, latest_calendar_day,
                    generated_at, payload_json, created_at, manifest_json,
                    identity_version, authoritative
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    dataset_key=excluded.dataset_key,
                    provider_uri=excluded.provider_uri,
                    freq=excluded.freq,
                    latest_calendar_day=excluded.latest_calendar_day,
                    generated_at=excluded.generated_at,
                    payload_json=excluded.payload_json,
                    manifest_json=excluded.manifest_json,
                    identity_version=excluded.identity_version,
                    authoritative=excluded.authoritative
                """,
                (
                    snapshot_id,
                    dataset_key,
                    provider_uri,
                    freq,
                    latest_calendar_day,
                    generated_at,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    created_at,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True) if manifest else None,
                    identity_version,
                    authoritative,
                ),
            )

    @staticmethod
    def _decode(row: Any) -> dict | None:
        if row is None:
            return None
        result = {key: row[key] for key in row.keys()}
        for source, target in (("payload_json", "payload"), ("manifest_json", "manifest")):
            raw = result.get(source)
            if raw:
                result[target] = json.loads(raw)
        return result

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        return self._decode(row)

    def get_latest_manifest(self, *, dataset_key: str, freq: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM data_snapshots
                WHERE dataset_key = ? AND freq = ? AND authoritative = 1
                ORDER BY latest_calendar_day DESC, created_at DESC
                LIMIT 1
                """,
                (str(dataset_key), str(freq)),
            ).fetchone()
        return self._decode(row)

    def get_latest(self, *, dataset_key: str, freq: str) -> dict | None:
        """Compatibility query that may return a non-authoritative legacy row."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM data_snapshots
                WHERE dataset_key = ? AND freq = ?
                ORDER BY latest_calendar_day DESC, created_at DESC
                LIMIT 1
                """,
                (str(dataset_key), str(freq)),
            ).fetchone()
        return self._decode(row)
