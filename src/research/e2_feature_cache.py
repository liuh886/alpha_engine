"""Optional per-invocation, source-bound E2 feature cache.

Only the reviewed serial CLI may enable this in a new runner/batch identity.
No disk persistence, untrusted pickle loading, cross-session sharing, held-out
feature preparation or bypass of frozen staging/Study Workspace validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")


@dataclass
class FeatureCacheSession:
    identity: str
    max_entries: int
    entries: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "status": "SCOPED_MEMORY_ONLY",
            "hits": self.hits, "misses": self.misses,
            "evictions": self.evictions, "resident_entries": len(self.entries),
            "by_kind": copy.deepcopy(self.by_kind),
            "research_only": True, "trade_ready": False,
        }


_ACTIVE: ContextVar[FeatureCacheSession | None] = ContextVar(
    "alpha_e2_feature_cache", default=None)


@contextmanager
def feature_cache_scope(*, batch_spec_sha256: str, max_entries: int = 16
                        ) -> Iterator[FeatureCacheSession]:
    """Activate cache only within one verified CLI invocation.

    Batch bytes are source/runner/spec bound by the existing batch verifier.
    Independently check the hash even if a new caller tries to bypass the CLI.
    """
    if (len(batch_spec_sha256) != 64 or
            any(ch not in "0123456789abcdef" for ch in batch_spec_sha256) or
            not 1 <= max_entries <= 64):
        raise ValueError("invalid scoped cache identity or bounded capacity")
    session = FeatureCacheSession(identity=batch_spec_sha256,
                                  max_entries=max_entries)
    token = _ACTIVE.set(session)
    try:
        yield session
    finally:
        _ACTIVE.reset(token)
        session.entries.clear()


def get_or_build(kind: str, inputs: dict[str, Any], build: Callable[[], T]) -> T:
    """Return an independent value to avoid mutation leaks between trials."""
    active = _ACTIVE.get()
    if active is None:
        return build()
    if kind not in ("slice", "train_features"):
        raise ValueError("unsupported feature-cache artifact kind")
    key_bytes = json.dumps({"identity": active.identity, "kind": kind,
                            "inputs": inputs}, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    key = hashlib.sha256(key_bytes).hexdigest()
    counters = active.by_kind.setdefault(kind, {"hits": 0, "misses": 0})
    if key in active.entries:
        active.hits += 1
        counters["hits"] += 1
        active.entries.move_to_end(key)
        return copy.deepcopy(active.entries[key])
    value = build()
    active.misses += 1
    counters["misses"] += 1
    active.entries[key] = copy.deepcopy(value)
    if len(active.entries) > active.max_entries:
        active.entries.popitem(last=False)
        active.evictions += 1
    return value
