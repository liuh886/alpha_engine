"""Lossless private transport for the existing canonical signal ledgers.

This is a checkpoint, not a second decision store or a live-writer cutover.
Only metadata receipts may be published; the ZIP itself is protected state.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from src.artifacts.strategy_signal_ledger import (
    MANIFEST_SCHEMA_VERSION,
    _decision_record_bytes,
    canonical_json_bytes,
    read_latest_evaluation,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog

SCHEMA = "strategy_signal_checkpoint_v1"
INDEX = "checkpoint.json"
MAX_BYTES = 90 * 1024 * 1024
MAX_FILES = 20000


class SignalCheckpointError(ValueError):
    """A checkpoint cannot be bound to the exact ledger and registry identities."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _models(catalog: Path) -> list[str]:
    return sorted(load_active_strategy_catalog(catalog).by_model_version_id)


def _member(name: str, models: list[str]) -> bool:
    parts = PurePosixPath(name).parts
    if "\\" in name or not parts or parts[0] not in models or any(p in {".", ".."} for p in parts):
        return False
    if name != "/".join(parts):
        return False
    if any(PureWindowsPath(part).is_reserved() for part in parts):
        return False
    if len(parts) == 2:
        return parts[1] in {"latest.json", "manifest.json", "README.md"}
    if len(parts) == 3 and parts[1] in {"records", "corrections"}:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-[0-9a-f]{20})?\.json", parts[2]))
    return bool(len(parts) == 4 and parts[1] == "deliveries"
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2])
        and re.fullmatch(r"[A-Za-z0-9_-]+\.json", parts[3]))


def _validate(root: Path, models: list[str]) -> None:
    for model in models:
        ledger = root / model
        latest = read_latest_evaluation(ledger, model_version_id=model)
        if latest is None:
            raise SignalCheckpointError(f"missing canonical ledger: {model}")
        raw = json.loads((ledger / "latest.json").read_bytes())
        manifest = json.loads((ledger / "manifest.json").read_bytes())
        if not isinstance(manifest, dict):
            raise SignalCheckpointError(f"canonical manifest is not an object: {model}")
        expected = {
            "schema_version": MANIFEST_SCHEMA_VERSION, "model_version_id": model,
            "latest_signal_date": raw["signal_date"], "latest_data_date": raw["latest_data_date"],
            "latest_fingerprint": raw["fingerprint"],
            "latest_record_sha256": _sha(_decision_record_bytes(raw)),
            "record_count": len(list((ledger / "records").glob("*.json"))),
            "correction_count": len(list((ledger / "corrections").glob("*.json"))),
            "research_only": True, "trade_ready": False, "append_only_records": True,
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise SignalCheckpointError(f"canonical manifest binding mismatch: {model}")
        sealed = ledger / ("corrections" if "correction" in raw else "records") / f"{raw['signal_date']}.json"
        if sealed.read_bytes() != (ledger / "latest.json").read_bytes():
            raise SignalCheckpointError(f"latest differs from sealed record: {model}")


def _excluded(root: Path, models: list[str]) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        raise SignalCheckpointError("ledger root does not match the exact active registry")
    children = list(root.iterdir())
    if (not set(models).issubset(p.name for p in children)
        or any(p.is_symlink() or not p.is_dir() for p in children)):
        raise SignalCheckpointError("ledger root does not match the exact active registry")
    return sorted(p.name for p in children if p.name not in models)


def _collect(root: Path, models: list[str]) -> dict[str, bytes]:
    _excluded(root, models)
    files: dict[str, bytes] = {}
    total = 0
    for path in sorted(p for model in models for p in (root / model).rglob("*")):
        if path.is_symlink():
            raise SignalCheckpointError("symlinks are not checkpoint members")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if not _member(name, models) or not path.is_file():
            raise SignalCheckpointError("unexpected canonical ledger member")
        with path.open("rb") as source:
            data = source.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise SignalCheckpointError("ledger checkpoint exceeds transport limits")
        files[name] = data
    return files


def pack_signal_checkpoint(ledger_root: Path, output: Path, *, catalog: Path, code_revision: str) -> dict[str, Any]:
    """Capture all active models; never omit a missing/broken ledger or overwrite evidence."""
    if not re.fullmatch(r"[0-9a-f]{40}", code_revision):
        raise SignalCheckpointError("code revision must be an exact Git SHA")
    if output.exists():
        raise SignalCheckpointError("checkpoint output already exists")
    catalog_digest = _sha(catalog.read_bytes())
    models = _models(catalog)
    excluded = _excluded(ledger_root, models)
    files = _collect(ledger_root, models)
    # Validate the captured bytes, rather than a concurrently changing source.
    with tempfile.TemporaryDirectory(prefix="alpha-ledger-pack-") as temporary:
        staging = Path(temporary)
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        _validate(staging, models)
    inventory = [{"path": name, "sha256": _sha(data), "byte_size": len(data)} for name, data in files.items()]
    index = {"schema_version": SCHEMA, "code_revision": code_revision,
        "strategy_catalog_sha256": catalog_digest, "models": models, "files": inventory,
        "scope": "active_registry_only", "excluded_nonactive_models": excluded,
        "research_only": True, "trade_ready": False}
    # Detect a writer changing the source while it was validated/collected.
    if (files != _collect(ledger_root, models) or _sha(catalog.read_bytes()) != catalog_digest
        or excluded != _excluded(ledger_root, models)):
        raise SignalCheckpointError("canonical ledger changed during checkpoint")
    index_bytes = canonical_json_bytes(index)
    if sum(len(data) for data in files.values()) + len(index_bytes) > MAX_BYTES:
        raise SignalCheckpointError("checkpoint index and members exceed transport limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as destination, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in [(INDEX, index_bytes), *files.items()]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    if output.stat().st_size > MAX_BYTES:
        raise SignalCheckpointError("compressed checkpoint exceeds transport limit")
    return {"schema_version": SCHEMA, "archive_sha256": _sha(output.read_bytes()),
        "archive_byte_size": output.stat().st_size, "strategy_catalog_sha256": index["strategy_catalog_sha256"],
        "code_revision": code_revision, "models": models, "member_count": len(files),
        "scope": "active_registry_only", "excluded_nonactive_models": excluded,
        "research_only": True, "trade_ready": False}


def restore_signal_checkpoint(archive_path: Path, output: Path, *, catalog: Path,
                              expected_sha256: str, expected_byte_size: int) -> dict[str, Any]:
    """Verify the entire pinned archive before exposing any bytes in a fresh workspace."""
    if output.exists():
        raise SignalCheckpointError("restore requires a fresh output directory")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or type(expected_byte_size) is not int or not 0 < expected_byte_size <= MAX_BYTES):
        raise SignalCheckpointError("invalid pinned checkpoint identity")
    with archive_path.open("rb") as source:
        archive_bytes = source.read(MAX_BYTES + 1)
    if len(archive_bytes) != expected_byte_size or _sha(archive_bytes) != expected_sha256:
        raise SignalCheckpointError("checkpoint archive digest or size mismatch")
    catalog_digest = _sha(catalog.read_bytes())
    models = _models(catalog)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        members = archive.infolist()
        names = [entry.filename for entry in members]
        if len(members) > MAX_FILES + 1 or len(names) != len(set(name.casefold() for name in names)) or INDEX not in names:
            raise SignalCheckpointError("checkpoint member closure is invalid")
        if sum(entry.file_size for entry in members) > MAX_BYTES:
            raise SignalCheckpointError("expanded checkpoint exceeds transport limit")
        for entry in members:
            mode = entry.external_attr >> 16
            if (entry.is_dir() or entry.flag_bits & 1 or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or entry.filename != entry.orig_filename
                or (entry.filename != INDEX and not _member(entry.filename, models))):
                raise SignalCheckpointError("unsafe checkpoint member")
        if archive.getinfo(INDEX).file_size > 4 * 1024 * 1024:
            raise SignalCheckpointError("checkpoint inventory exceeds transport limit")
        index = json.loads(archive.read(INDEX))
        if (not isinstance(index, dict) or index.get("schema_version") != SCHEMA
            or index.get("models") != models or index.get("strategy_catalog_sha256") != catalog_digest
            or index.get("scope") != "active_registry_only"
            or not isinstance(index.get("excluded_nonactive_models"), list)
            or not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name)
                       and name not in models for name in index["excluded_nonactive_models"])
            or index.get("research_only") is not True or index.get("trade_ready") is not False
            or not re.fullmatch(r"[0-9a-f]{40}", str(index.get("code_revision", "")))):
            raise SignalCheckpointError("checkpoint registry or research identity mismatch")
        inventory = index.get("files")
        if not isinstance(inventory, list) or not all(isinstance(row, dict)
            and set(row) == {"path", "sha256", "byte_size"} and isinstance(row["path"], str)
            and _member(row["path"], models) and isinstance(row["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            and type(row["byte_size"]) is int and 0 <= row["byte_size"] <= MAX_BYTES for row in inventory):
            raise SignalCheckpointError("checkpoint inventory is invalid")
        paths = [row.get("path") for row in inventory]
        if len(paths) != len(set(paths)) or set(names) != {INDEX, *paths}:
            raise SignalCheckpointError("checkpoint inventory does not close over the archive")
        files = {}
        for row in inventory:
            name = row["path"]
            data = archive.read(name)
            if row.get("sha256") != _sha(data) or row.get("byte_size") != len(data):
                raise SignalCheckpointError("checkpoint member binding mismatch")
            files[name] = data
    # Stage and validate canonical semantics before creating the requested target.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="alpha-ledger-restore-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        _validate(staging, models)
        if _collect(staging, models) != files:
            raise SignalCheckpointError("restored staging bytes differ from checkpoint inventory")
        if _sha(catalog.read_bytes()) != catalog_digest:
            raise SignalCheckpointError("strategy registry changed during restoration")
        # mkdir is exclusive: an existing caller directory is never replaced.
        output.mkdir(mode=0o700)
        for name, data in files.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o600)
    return {"schema_version": SCHEMA, "status": "restored", "archive_sha256": expected_sha256,
        "archive_byte_size": expected_byte_size, "strategy_catalog_sha256": index["strategy_catalog_sha256"],
        "code_revision": index["code_revision"], "models": models, "member_count": len(files),
        "scope": "active_registry_only", "excluded_nonactive_models": index["excluded_nonactive_models"],
        "research_only": True, "trade_ready": False}
