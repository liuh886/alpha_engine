"""Truthful identity evidence for partial market-data providers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_effective_provider_universe(
    provider_dir: str | Path,
    markets: list[str] | set[str] | tuple[str, ...],
) -> dict[str, list[str]]:
    """Read the symbols actually present in market-specific instrument files."""

    provider = Path(provider_dir)
    result: dict[str, list[str]] = {}
    for raw_market in sorted({str(item).lower() for item in markets}):
        path = provider / "instruments" / f"{raw_market}.txt"
        symbols: list[str] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
                line = line.strip()
                if not line:
                    continue
                symbol = line.split("\t", 1)[0].strip().upper()
                if symbol:
                    symbols.append(symbol)
        result[raw_market] = sorted(set(symbols))
    return result


def build_universe_evidence(
    *,
    configured: dict[str, list[str]],
    effective: dict[str, list[str]],
) -> dict[str, Any]:
    """Build configured/effective/missing/extra universe identity evidence."""

    configured_normalized = {
        str(market).lower(): sorted({str(symbol).upper() for symbol in symbols})
        for market, symbols in configured.items()
    }
    effective_normalized = {
        str(market).lower(): sorted({str(symbol).upper() for symbol in symbols})
        for market, symbols in effective.items()
    }
    markets = sorted(set(configured_normalized) | set(effective_normalized))
    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for market in markets:
        configured_set = set(configured_normalized.get(market, []))
        effective_set = set(effective_normalized.get(market, []))
        missing[market] = sorted(configured_set - effective_set)
        extra[market] = sorted(effective_set - configured_set)

    return {
        "configured": configured_normalized,
        "effective": effective_normalized,
        "missing": missing,
        "extra": extra,
        "configured_sha256": canonical_sha256(configured_normalized),
        "effective_sha256": canonical_sha256(effective_normalized),
    }


def provider_attempts_evidence(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "sha256": None, "present": False}
    evidence_path = Path(path)
    if not evidence_path.is_file():
        return {"path": str(evidence_path), "sha256": None, "present": False}
    return {
        "path": str(evidence_path.resolve()),
        "sha256": file_sha256(evidence_path),
        "present": True,
    }
