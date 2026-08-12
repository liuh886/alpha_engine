"""Project accepted Formal Bundle v2 runs into Market Evidence event inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    validate_catalog,
    validate_manifest,
)


class FormalMarketEventError(ValueError):
    """Raised when formal Bundle v2 evidence cannot be projected safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalMarketEventError(f"invalid formal Bundle v2 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalMarketEventError(f"formal Bundle v2 object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: object, *, label: str) -> Path:
    text = str(relative or "")
    candidate = Path(text)
    if not text or candidate.is_absolute() or ".." in candidate.parts:
        raise FormalMarketEventError(f"unsafe {label}: {text!r}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise FormalMarketEventError(f"{label} escaped formal Bundle v2 root: {text!r}")
    return resolved


def _section_payload(
    bundle_dir: Path,
    manifest: Mapping[str, Any],
    section_id: str,
    *,
    required: bool,
) -> object | None:
    rows = manifest.get("sections")
    if not isinstance(rows, list):
        raise FormalMarketEventError("formal Bundle v2 sections are missing")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("section_id") == section_id
    ]
    if len(matches) != 1:
        raise FormalMarketEventError(
            f"formal Bundle v2 section identity is ambiguous: {section_id}"
        )
    section = matches[0]
    if section.get("availability_status") != "available":
        if required:
            raise FormalMarketEventError(
                f"required formal Bundle v2 section is unavailable: {section_id}"
            )
        return None
    path = _safe_path(bundle_dir, section.get("path"), label=f"{section_id} path")
    if not path.is_file():
        raise FormalMarketEventError(f"formal Bundle v2 section is missing: {path}")
    expected_sha = str(section.get("sha256") or "")
    expected_size = section.get("byte_size")
    if _sha256(path) != expected_sha or path.stat().st_size != expected_size:
        raise FormalMarketEventError(
            f"formal Bundle v2 section integrity mismatch: {section_id}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalMarketEventError(
            f"invalid formal Bundle v2 section JSON: {path}"
        ) from exc


def load_formal_market_runs(formal_root: Path, market: str) -> list[dict[str, Any]]:
    """Load all and only accepted formal runs for one market from Bundle v2."""

    root = formal_root.resolve()
    catalog_path = root / "catalog.json"
    catalog = _load_json(catalog_path)
    try:
        validate_catalog(catalog)
    except ModelRunBundleV2Error as exc:
        raise FormalMarketEventError(str(exc)) from exc
    if catalog.get("channel") != "formal":
        raise FormalMarketEventError("Market Evidence requires the formal Bundle v2 catalog")

    records = catalog.get("records")
    if not isinstance(records, list):
        raise FormalMarketEventError("formal Bundle v2 catalog records are missing")

    projected: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise FormalMarketEventError("formal Bundle v2 catalog record is invalid")
        manifest_path = _safe_path(
            root,
            record.get("manifest_path"),
            label="formal manifest path",
        )
        if not manifest_path.is_file():
            raise FormalMarketEventError(f"formal manifest is missing: {manifest_path}")
        if _sha256(manifest_path) != str(record.get("manifest_sha256") or ""):
            raise FormalMarketEventError(
                f"formal manifest digest mismatch: {record.get('model_version_id')}"
            )
        manifest = _load_json(manifest_path)
        try:
            validate_manifest(manifest)
        except ModelRunBundleV2Error as exc:
            raise FormalMarketEventError(str(exc)) from exc

        identity_pairs = (
            ("model_family_id", "model_family_id"),
            ("model_version_id", "model_version_id"),
            ("run_id", "run_id"),
            ("bundle_id", "bundle_id"),
            ("publication_status", "publication_status"),
        )
        for manifest_key, record_key in identity_pairs:
            if manifest.get(manifest_key) != record.get(record_key):
                raise FormalMarketEventError(
                    "formal catalog/manifest identity mismatch: "
                    f"{record.get('model_version_id')}/{manifest_key}"
                )

        comparability = manifest.get("comparability_key")
        if not isinstance(comparability, Mapping):
            raise FormalMarketEventError("formal comparability key is missing")
        if str(comparability.get("market") or "").lower() != market.lower():
            continue

        bundle_dir = manifest_path.parent
        summary = _section_payload(bundle_dir, manifest, "summary", required=True)
        if not isinstance(summary, Mapping):
            raise FormalMarketEventError("formal summary section must be an object")
        portfolio = _section_payload(bundle_dir, manifest, "portfolio", required=False)
        trades = _section_payload(bundle_dir, manifest, "trades", required=False)

        positions: list[Any] = []
        if portfolio is not None:
            if not isinstance(portfolio, Mapping):
                raise FormalMarketEventError("formal portfolio section must be an object")
            raw_positions = portfolio.get("positions", [])
            if not isinstance(raw_positions, list):
                raise FormalMarketEventError("formal portfolio positions must be a list")
            positions = raw_positions

        trade_rows: list[Any] = []
        if trades is not None:
            if not isinstance(trades, list):
                raise FormalMarketEventError("formal trades section must be a list")
            trade_rows = trades

        model_id = str(manifest["model_version_id"])
        projected.append(
            {
                "model_id": model_id,
                "display_name": str(summary.get("display_name") or model_id),
                "backtest_id": str(manifest["run_id"]),
                "bundle_id": str(manifest["bundle_id"]),
                "evidence_cutoff": str(manifest["evidence_cutoff"]),
                "positions": positions,
                "trades": trade_rows,
                "research_only": True,
                "trade_ready": False,
            }
        )

    if not projected:
        raise FormalMarketEventError(f"no accepted formal Bundle v2 runs found for {market}")
    projected.sort(key=lambda row: str(row["model_id"]))
    return projected
