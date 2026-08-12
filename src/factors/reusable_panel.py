"""Content-addressed reuse for governed Alpha158 factor panels."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.factors.panel import FactorEvaluator, build_alpha158_panel
from src.factors.sets.qlib_alpha158 import load_alpha158_definitions


class ReusableFactorPanelError(ValueError):
    """Raised when a reusable factor panel is stale, tampered, or malformed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReusableFactorPanelError(f"mapping required: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReusableFactorPanelError(f"JSON object required: {path}")
    return payload


def _resolve_repo_file(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ReusableFactorPanelError(f"factor-panel input escapes repository root: {raw}")
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _bounded_panel_file(output: Path, relative: str) -> Path:
    path = (output / relative).resolve()
    if not path.is_relative_to(output.resolve()):
        raise ReusableFactorPanelError(f"factor-panel file escapes output root: {relative}")
    return path


def factor_panel_input_identity(
    *,
    root: str | Path,
    contract_path: str | Path,
    provider_uri: str | Path,
    market: str,
    start: str,
    cutoff: str,
) -> str:
    """Return the immutable identity of one Alpha158 materialization request."""

    repo = Path(root).resolve()
    contract_file = _resolve_repo_file(repo, contract_path)
    contract = _load_mapping(contract_file)
    market_key = str(market).lower()
    market_cfg = contract.get("markets", {}).get(market_key)
    if not isinstance(market_cfg, dict):
        raise ReusableFactorPanelError(f"market is not declared: {market_key}")
    pool_file = _resolve_repo_file(repo, str(market_cfg.get("pool_spec", "")))

    provider = Path(provider_uri).resolve()
    provider_manifest = provider / "provider_manifest.json"
    if not provider_manifest.is_file():
        raise FileNotFoundError(provider_manifest)
    role_policy = contract.get("provider_role_policy", {})
    if not isinstance(role_policy, dict):
        raise ReusableFactorPanelError("provider_role_policy must be a mapping")
    source_role = provider / str(
        role_policy.get("source_role_manifest", "source_role_manifest.json")
    )
    source_role_sha256 = _sha256(source_role) if source_role.is_file() else None

    definitions = load_alpha158_definitions()
    catalog_identity = hashlib.sha256(
        _canonical_json(
            {
                "factor_count": len(definitions),
                "definitions": [
                    {
                        "factor_id": row.factor_id,
                        "implementation_hash": row.implementation_hash,
                    }
                    for row in definitions
                ],
            }
        )
    ).hexdigest()
    implementation_files = (
        Path(__file__).resolve(),
        Path(__file__).with_name("panel.py").resolve(),
        Path(__file__).with_name("sets") / "qlib_alpha158.py",
    )
    payload = {
        "schema_version": "1.0",
        "market": market_key,
        "pool_id": str(market_cfg.get("pool_id", "")),
        "start": str(start),
        "cutoff": str(cutoff),
        "contract_sha256": _sha256(contract_file),
        "pool_sha256": _sha256(pool_file),
        "provider_manifest_sha256": _sha256(provider_manifest),
        "source_role_manifest_sha256": source_role_sha256,
        "catalog_identity_sha256": catalog_identity,
        "implementation_sha256": {
            path.name: _sha256(path) for path in implementation_files
        },
        "research_only": True,
        "trade_ready": False,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _normalize_gzip(path: Path) -> None:
    """Recompress existing CSV bytes with a stable gzip header."""

    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(payload)


def _verify_reusable_tree(
    *,
    output: Path,
    manifest: Mapping[str, Any],
    expected_identity: str,
) -> None:
    if manifest.get("input_identity_sha256") != expected_identity:
        raise ReusableFactorPanelError("factor-panel input identity mismatch")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise ReusableFactorPanelError("factor-panel research boundary changed")

    catalog = output / "factor_catalog.json"
    expected_catalog = str(manifest.get("catalog_sha256", ""))
    if not catalog.is_file() or _sha256(catalog) != expected_catalog:
        raise ReusableFactorPanelError("factor-panel catalog hash mismatch")

    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ReusableFactorPanelError("factor-panel files manifest must be a mapping")
    for relative, expected_sha in files.items():
        path = _bounded_panel_file(output, str(relative))
        if not path.is_file() or _sha256(path) != str(expected_sha):
            raise ReusableFactorPanelError(f"factor-panel file hash mismatch: {relative}")


def _seal_materialized_panel(
    *,
    output: Path,
    manifest: dict[str, Any],
    input_identity: str,
) -> dict[str, Any]:
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        files = {}
    normalized: dict[str, str] = {}
    for relative in sorted(files):
        path = _bounded_panel_file(output, str(relative))
        if not path.is_file():
            raise ReusableFactorPanelError(f"factor-panel file is missing: {relative}")
        if path.suffix == ".gz":
            _normalize_gzip(path)
        normalized[str(relative)] = _sha256(path)

    sealed = dict(manifest)
    sealed["input_identity_sha256"] = input_identity
    if files:
        sealed["files"] = normalized
    path = output / "factor_panel_manifest.json"
    path.write_text(
        json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    _verify_reusable_tree(
        output=output,
        manifest=sealed,
        expected_identity=input_identity,
    )
    return sealed


def build_reusable_alpha158_panel(
    *,
    root: str | Path,
    contract_path: str | Path,
    provider_uri: str | Path,
    market: str,
    start: str,
    cutoff: str,
    output_root: str | Path,
    evaluator: FactorEvaluator | None = None,
) -> dict[str, Any]:
    """Reuse an exact verified panel or rebuild it from the canonical materializer."""

    output = Path(output_root).resolve()
    identity = factor_panel_input_identity(
        root=root,
        contract_path=contract_path,
        provider_uri=provider_uri,
        market=market,
        start=start,
        cutoff=cutoff,
    )
    manifest_path = output / "factor_panel_manifest.json"
    if manifest_path.is_file():
        existing = _load_json(manifest_path)
        if existing.get("input_identity_sha256") == identity:
            _verify_reusable_tree(
                output=output,
                manifest=existing,
                expected_identity=identity,
            )
            return existing

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_alpha158_panel(
        root=root,
        contract_path=contract_path,
        provider_uri=provider_uri,
        market=market,
        start=start,
        cutoff=cutoff,
        output_root=output,
        evaluator=evaluator,
    )
    return _seal_materialized_panel(
        output=output,
        manifest=manifest,
        input_identity=identity,
    )
