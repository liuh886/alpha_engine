"""Market-specific Qlib provider identity and path helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_MARKETS = ("cn", "us", "hk")
PROVIDER_MANIFEST_SCHEMA_VERSION = "1.0"


def normalize_provider_market(market: str) -> str:
    value = str(market).strip().lower()
    if value not in SUPPORTED_MARKETS:
        raise ValueError(f"unsupported provider market: {market}")
    return value


def market_provider_path(repository_root: str | Path, market: str) -> Path:
    """Return the canonical market-specific provider directory."""

    root = Path(repository_root).resolve()
    return root / "data" / "providers" / normalize_provider_market(market)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    """Hash file names and bytes for a deterministic provider subtree."""

    digest = hashlib.sha256()
    if not path.is_dir():
        return digest.hexdigest()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _identity_sha256(payload: dict[str, Any]) -> str:
    identity = {
        key: value
        for key, value in payload.items()
        if key != "provider_identity_sha256"
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_provider_manifest(
    provider_dir: str | Path,
    *,
    market: str,
    source_csv_files: Iterable[str | Path],
) -> dict[str, Any]:
    """Write a deterministic identity manifest for one market provider."""

    provider = Path(provider_dir).resolve()
    market_key = normalize_provider_market(market)
    calendar_path = provider / "calendars" / "day.txt"
    instrument_path = provider / "instruments" / f"{market_key}.txt"
    if not calendar_path.is_file():
        raise FileNotFoundError(f"provider calendar is missing: {calendar_path}")
    if not instrument_path.is_file():
        raise FileNotFoundError(f"provider instruments are missing: {instrument_path}")

    calendar_days = [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    instrument_rows = [
        line.strip()
        for line in instrument_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sources = []
    for raw_path in sorted(Path(item).resolve() for item in source_csv_files):
        if not raw_path.is_file():
            raise FileNotFoundError(f"provider source CSV is missing: {raw_path}")
        sources.append(
            {
                "name": raw_path.name,
                "sha256": _sha256_file(raw_path),
            }
        )

    payload: dict[str, Any] = {
        "schema_version": PROVIDER_MANIFEST_SCHEMA_VERSION,
        "market": market_key,
        "calendar": {
            "path": "calendars/day.txt",
            "sha256": _sha256_file(calendar_path),
            "session_count": len(calendar_days),
            "first_day": calendar_days[0] if calendar_days else None,
            "last_day": calendar_days[-1] if calendar_days else None,
        },
        "instruments": {
            "path": f"instruments/{market_key}.txt",
            "sha256": _sha256_file(instrument_path),
            "count": len(instrument_rows),
        },
        "features_sha256": _sha256_tree(provider / "features"),
        "source_csvs": sources,
    }
    payload["provider_identity_sha256"] = _identity_sha256(payload)
    manifest_path = provider / "provider_manifest.json"
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def load_provider_manifest(
    provider_dir: str | Path,
    *,
    expected_market: str | None = None,
    required: bool = True,
    verify_files: bool = True,
) -> dict[str, Any] | None:
    """Load and verify a market provider manifest."""

    provider = Path(provider_dir).resolve()
    manifest_path = provider / "provider_manifest.json"
    if not manifest_path.is_file():
        if required:
            raise FileNotFoundError(f"provider manifest is missing: {manifest_path}")
        return None

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider manifest must be a JSON object")
    market = normalize_provider_market(str(payload.get("market", "")))
    if expected_market is not None and market != normalize_provider_market(expected_market):
        raise ValueError(
            f"provider manifest market mismatch: expected={expected_market} actual={market}"
        )
    expected_identity = _identity_sha256(payload)
    if payload.get("provider_identity_sha256") != expected_identity:
        raise ValueError("provider manifest identity hash mismatch")

    if verify_files:
        calendar = payload.get("calendar")
        instruments = payload.get("instruments")
        if not isinstance(calendar, dict) or not isinstance(instruments, dict):
            raise ValueError("provider manifest calendar/instruments metadata is missing")
        calendar_path = provider / str(calendar.get("path", ""))
        instrument_path = provider / str(instruments.get("path", ""))
        if not calendar_path.is_file() or _sha256_file(calendar_path) != calendar.get("sha256"):
            raise ValueError("provider calendar hash mismatch")
        if not instrument_path.is_file() or _sha256_file(instrument_path) != instruments.get(
            "sha256"
        ):
            raise ValueError("provider instrument hash mismatch")
        if _sha256_tree(provider / "features") != payload.get("features_sha256"):
            raise ValueError("provider feature-tree hash mismatch")

    return payload
