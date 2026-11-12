"""Validation helpers for append-only prospective research stores."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path


class AppendOnlyStoreError(ValueError):
    """Raised when a reproduced store rewrites accepted history."""


def records_equivalent(
    accepted: object,
    candidate: object,
    *,
    rel_tol: float = 1e-12,
    abs_tol: float = 1e-12,
) -> bool:
    """Compare a reproduced record while tolerating only last-bit float noise.

    Accepted observations can be sealed on a different Python/BLAS micro-version
    than the reproduction. A one-ulp difference in a derived float is not a
    history revision, but an exact byte comparison turns it into a permanent
    workflow failure. Every structural field, string, boolean and integer still
    compares exactly; finite floats may differ only within the given tolerance.
    """

    if isinstance(accepted, Mapping) and isinstance(candidate, Mapping):
        return accepted.keys() == candidate.keys() and all(
            records_equivalent(accepted[key], candidate[key], rel_tol=rel_tol, abs_tol=abs_tol)
            for key in accepted
        )
    if isinstance(accepted, list) and isinstance(candidate, list):
        return len(accepted) == len(candidate) and all(
            records_equivalent(left, right, rel_tol=rel_tol, abs_tol=abs_tol)
            for left, right in zip(accepted, candidate, strict=True)
        )
    if isinstance(accepted, bool) or isinstance(candidate, bool):
        return type(accepted) is type(candidate) and accepted == candidate
    if isinstance(accepted, float) and isinstance(candidate, float):
        return math.isclose(accepted, candidate, rel_tol=rel_tol, abs_tol=abs_tol)
    return type(accepted) is type(candidate) and accepted == candidate


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
