"""Validation helpers for append-only prospective research stores."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


class AppendOnlyStoreError(ValueError):
    """Raised when a reproduced store rewrites accepted history."""


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AppendOnlyStoreError(f"expected JSON object: {path}")
    return value


def _assert_namespace_prefix(current_root: Path, candidate_root: Path, name: str) -> None:
    current = current_root / name
    if not current.exists():
        return
    for path in sorted(current.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(current_root)
        candidate = candidate_root / relative
        if not candidate.is_file():
            raise AppendOnlyStoreError(f"accepted append-only record disappeared: {relative}")
        if path.read_bytes() != candidate.read_bytes():
            raise AppendOnlyStoreError(f"accepted append-only record drifted: {relative}")


def _assert_ledger_prefix(current_root: Path, candidate_root: Path) -> None:
    current = current_root / "ledger.csv"
    if not current.is_file():
        return
    candidate = candidate_root / "ledger.csv"
    if not candidate.is_file():
        raise AppendOnlyStoreError("reproduced store is missing ledger.csv")
    accepted = current.read_bytes()
    reproduced = candidate.read_bytes()
    if not reproduced.startswith(accepted):
        raise AppendOnlyStoreError("reproduced ledger rewrites the accepted ledger prefix")


def _assert_digest_mapping_prefix(
    current: Mapping[str, object], candidate: Mapping[str, object], key: str
) -> None:
    accepted = current.get(key)
    reproduced = candidate.get(key)
    if accepted is None:
        return
    if not isinstance(accepted, Mapping) or not isinstance(reproduced, Mapping):
        raise AppendOnlyStoreError(f"manifest {key} must remain an object")
    for identity, digest in accepted.items():
        if reproduced.get(identity) != digest:
            raise AppendOnlyStoreError(f"manifest {key} drifted for {identity}")


def validate_append_only_store_prefix(current_root: Path, candidate_root: Path) -> None:
    """Require a reproduction to preserve all accepted records byte-for-byte.

    A candidate may contain additional tail observations/outcomes. Derived files
    such as README, manifest, scorecard and ledger totals are allowed to advance
    only when the immutable record prefix itself remains unchanged.
    """

    if not current_root.is_dir() or not candidate_root.is_dir():
        raise AppendOnlyStoreError("both current and reproduced stores must exist")

    for namespace in ("observations", "outcomes"):
        _assert_namespace_prefix(current_root, candidate_root, namespace)
    _assert_ledger_prefix(current_root, candidate_root)

    current_manifest = _object(current_root / "manifest.json")
    candidate_manifest = _object(candidate_root / "manifest.json")
    for field, expected in (
        ("append_only", True),
        ("research_only", True),
        ("trade_ready", False),
    ):
        if current_manifest.get(field) != expected or candidate_manifest.get(field) != expected:
            raise AppendOnlyStoreError(f"manifest boundary changed: {field}")

    for count_key in ("observation_count", "outcome_count"):
        accepted = current_manifest.get(count_key, 0)
        reproduced = candidate_manifest.get(count_key, 0)
        if not isinstance(accepted, int) or isinstance(accepted, bool):
            raise AppendOnlyStoreError(f"current {count_key} is invalid")
        if not isinstance(reproduced, int) or isinstance(reproduced, bool):
            raise AppendOnlyStoreError(f"candidate {count_key} is invalid")
        if reproduced < accepted:
            raise AppendOnlyStoreError(f"candidate {count_key} regressed")

    for mapping_key in ("observation_sha256", "outcome_sha256"):
        _assert_digest_mapping_prefix(current_manifest, candidate_manifest, mapping_key)
