"""Content-addressed cache governance for formal-refresh market providers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.data.market_provider import (
    load_provider_manifest,
    verify_provider_manifest_file_identities,
)
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    SelectedPoolPricePublicationError,
    verify_selected_pool_price_publication_manifest,
)


class FormalProviderCacheError(ValueError):
    """Raised when cached provider evidence is incomplete or has drifted."""


CACHE_SCHEMA_VERSION = "1.1.0"
CONTRACT_PATHS = (
    "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml",
    "configs/pools/selected_pool_registry_v1.yaml",
    "configs/pools/reference_instrument_registry_v1.yaml",
    "pyproject.toml",
    "uv.lock",
    "scripts/build_market_providers.py",
    "scripts/dump_bin.py",
    "scripts/govern_formal_provider_cache.py",
    "scripts/data/refresh_selected_pool_prices.py",
    "scripts/data/refresh_selected_pool_prices_v2.py",
    "src/artifacts/formal_provider_cache.py",
    "src/data/provider_catalog.py",
    "src/data/router.py",
    "src/data/validation/schema.py",
    "src/research/selected_pool_guard.py",
)
MARKET_UNIVERSE_PATHS = {
    "us": "configs/research_universes/us_selected_equities_v2.yaml",
    "cn": "configs/research_universes/cn_selected_equities_v3.yaml",
}
DEFAULT_AUXILIARIES = {
    "us": ("QQQI", "TQQQ", "CGDV", "SGOV", "TYGO"),
    "cn": ("515180",),
}
# Publication-only serializers cannot change provider source bytes.
PROVIDER_CACHE_EXCLUDED_PATHS = frozenset({"src/data/model_data_bundle.py"})


@dataclass(frozen=True)
class _TreeIndex:
    file_hashes: dict[str, str]
    identity_sha256: str
    raw_subtree_sha256: str | None = None

    @property
    def file_count(self) -> int:
        return len(self.file_hashes)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(payload)
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalProviderCacheError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalProviderCacheError(f"JSON object required: {path}")
    return payload


def _relative_file_hashes(root: Path, paths: Sequence[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(paths):
        if not path.is_file():
            raise FormalProviderCacheError(f"cache contract input is missing: {path}")
        hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
    return hashes


def build_provider_cache_contract(
    *,
    repository_root: Path,
    market: str,
    start: str,
    requested_cutoff: str,
) -> dict[str, Any]:
    """Bind a reusable provider build to all code and governance inputs."""

    root = repository_root.resolve()
    market = market.strip().lower()
    if market not in MARKET_UNIVERSE_PATHS:
        raise FormalProviderCacheError(f"unsupported market: {market}")
    configured = [root / value for value in CONTRACT_PATHS]
    configured.append(root / MARKET_UNIVERSE_PATHS[market])
    configured.extend(sorted((root / "src/data/adapters").glob("*.py")))
    configured.extend(
        path
        for path in sorted((root / "src/data").glob("*.py"))
        if path.relative_to(root).as_posix() not in PROVIDER_CACHE_EXCLUDED_PATHS
    )
    payload: dict[str, Any] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "evidence_type": "formal_provider_cache_contract",
        "market": market,
        "start": start,
        "requested_cutoff": requested_cutoff,
        "refresh_mode": "incremental_from_governed_seed",
        "max_rounds": 3,
        "auxiliary_symbols": list(DEFAULT_AUXILIARIES[market]),
        "inputs": _relative_file_hashes(root, configured),
        "research_only": True,
        "trade_ready": False,
    }
    payload["contract_sha256"] = _sha256_bytes(_canonical_json(payload))
    return payload


def cache_key(contract: Mapping[str, Any]) -> str:
    market = str(contract.get("market", ""))
    cutoff = str(contract.get("requested_cutoff", ""))
    digest = str(contract.get("contract_sha256", ""))
    if not market or not cutoff or len(digest) != 64:
        raise FormalProviderCacheError("provider cache contract identity is incomplete")
    return f"formal-provider-{CACHE_SCHEMA_VERSION}-{market}-{cutoff}-{digest}"


def _index_tree(root: Path, *, raw_subtree: str | None = None) -> _TreeIndex:
    if not root.is_dir():
        raise FormalProviderCacheError(f"provider cache tree is missing: {root}")
    paths = [path for path in sorted(root.rglob("*")) if path.is_file()]
    if not paths:
        raise FormalProviderCacheError(f"provider cache tree is empty: {root}")
    subtree_root = root / raw_subtree if raw_subtree is not None else None
    subtree_digest = hashlib.sha256() if subtree_root is not None else None
    file_hashes: dict[str, str] = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        file_digest = hashlib.sha256()
        subtree_relative: bytes | None = None
        if subtree_root is not None:
            try:
                subtree_relative = path.relative_to(subtree_root).as_posix().encode("utf-8")
            except ValueError:
                pass
            else:
                assert subtree_digest is not None
                subtree_digest.update(len(subtree_relative).to_bytes(8, "big"))
                subtree_digest.update(subtree_relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
                if subtree_relative is not None:
                    assert subtree_digest is not None
                    subtree_digest.update(chunk)
        file_hashes[relative] = file_digest.hexdigest()
    records = [
        {"path": relative, "sha256": file_hashes[relative]}
        for relative in file_hashes
    ]
    return _TreeIndex(
        file_hashes=file_hashes,
        identity_sha256=_sha256_bytes(_canonical_json({"records": records})),
        raw_subtree_sha256=(
            subtree_digest.hexdigest() if subtree_digest is not None else None
        ),
    )


def _validate_manifest(
    provider_root: Path,
    contract: Mapping[str, Any],
    *,
    csv_index: _TreeIndex,
    qlib_index: _TreeIndex,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    manifest_path = provider_root / "artifacts" / "selected_pool_price_refresh_manifest.json"
    publication_path = provider_root / "artifacts" / PUBLICATION_MANIFEST_NAME
    manifest = _load_json(manifest_path)
    market = str(contract.get("market", ""))
    if str(manifest.get("market", "")) != market:
        raise FormalProviderCacheError("cached provider market does not match contract")
    if str(manifest.get("start", "")) != str(contract.get("start", "")):
        raise FormalProviderCacheError("cached provider start does not match contract")
    if str(manifest.get("cutoff", "")) != str(contract.get("requested_cutoff", "")):
        raise FormalProviderCacheError("cached provider cutoff does not match contract")
    if manifest.get("status") != "selected_pool_price_refresh_ready":
        raise FormalProviderCacheError("cached provider is not refresh ready")
    if manifest.get("promotion_eligible") is not True:
        raise FormalProviderCacheError("cached provider is not promotion eligible")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise FormalProviderCacheError("cached provider crossed research boundary")
    records = [row for row in manifest.get("records", []) if isinstance(row, dict)]
    symbols = [str(row.get("symbol", "")).strip().upper() for row in records]
    if not symbols or len(symbols) != len(set(symbols)):
        raise FormalProviderCacheError("cached provider symbols are incomplete or duplicated")
    candidate_symbols = {
        str(value).strip().upper()
        for value in manifest.get("candidate_symbols", [])
        if str(value).strip()
    }
    if len(candidate_symbols) != int(manifest.get("candidate_count", 0)):
        raise FormalProviderCacheError("cached candidate identity is incomplete")
    if not candidate_symbols.issubset(set(symbols)):
        raise FormalProviderCacheError("cached candidates are outside the provider symbols")
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        expected = str(record.get("output_sha256", ""))
        actual = csv_index.file_hashes.get(f"{symbol}.csv")
        if len(expected) != 64 or actual is None:
            raise FormalProviderCacheError(f"cached source identity is missing: {symbol}")
        if actual != expected:
            raise FormalProviderCacheError(f"cached source hash mismatch: {symbol}")
    try:
        publication = verify_selected_pool_price_publication_manifest(
            publication_path, manifest
        )
        qlib_manifest = load_provider_manifest(
            provider_root / "data" / "providers" / market,
            expected_market=market,
            verify_files=False,
        )
        if isinstance(qlib_manifest, dict):
            verify_provider_manifest_file_identities(
                qlib_manifest,
                file_hashes=qlib_index.file_hashes,
                features_sha256=str(qlib_index.raw_subtree_sha256),
            )
    except (SelectedPoolPricePublicationError, FileNotFoundError, ValueError) as exc:
        raise FormalProviderCacheError(f"cached provider evidence is invalid: {exc}") from exc
    if not isinstance(qlib_manifest, dict):
        raise FormalProviderCacheError("cached Qlib provider manifest is missing")
    provider_identity = str(manifest.get("provider_identity_sha256", ""))
    if (
        str(publication.get("provider_identity_sha256", "")) != provider_identity
        or str(qlib_manifest.get("provider_identity_sha256", "")) != provider_identity
    ):
        raise FormalProviderCacheError("provider identity does not match Qlib bytes")
    qlib_sources = qlib_manifest.get("source_csvs")
    if not isinstance(qlib_sources, list):
        raise FormalProviderCacheError("cached Qlib source identities are missing")
    expected_sources = [
        {"name": relative, "sha256": csv_index.file_hashes[relative]}
        for relative in sorted(csv_index.file_hashes)
        if "/" not in relative and Path(relative).suffix.lower() == ".csv"
    ]
    if qlib_sources != expected_sources:
        raise FormalProviderCacheError("cached Qlib source identities do not match CSV bytes")
    return manifest_path, publication_path, manifest, publication


def seal_provider_cache(
    *,
    provider_root: Path,
    contract: Mapping[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    """Validate a fresh provider build and seal exact reusable bytes."""

    provider_root = provider_root.resolve()
    market = str(contract["market"])
    csv_index = _index_tree(provider_root / "data" / "csv_source")
    qlib_index = _index_tree(
        provider_root / "data" / "providers" / market,
        raw_subtree="features",
    )
    manifest_path, publication_path, manifest, publication = _validate_manifest(
        provider_root,
        contract,
        csv_index=csv_index,
        qlib_index=qlib_index,
    )
    receipt: dict[str, Any] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "evidence_type": "formal_provider_cache_receipt",
        "contract_sha256": str(contract["contract_sha256"]),
        "provider_manifest_sha256": _sha256_file(manifest_path),
        "publication_manifest_sha256": _sha256_file(publication_path),
        "publication_identity_sha256": str(
            publication.get("publication_identity_sha256", "")
        ),
        "provider_identity_sha256": str(manifest.get("provider_identity_sha256", "")),
        "market": market,
        "requested_cutoff": str(contract["requested_cutoff"]),
        "provider_cutoff": str(manifest.get("cutoff", "")),
        "candidate_count": int(manifest.get("candidate_count", 0)),
        "symbol_count": len(manifest.get("records", [])),
        "csv_tree_sha256": csv_index.identity_sha256,
        "csv_file_count": csv_index.file_count,
        "qlib_tree_sha256": qlib_index.identity_sha256,
        "qlib_file_count": qlib_index.file_count,
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(receipt_path, receipt)
    return receipt


def verify_provider_cache(
    *,
    provider_root: Path,
    contract: Mapping[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    """Fail closed unless a restored cache matches its contract and receipt."""

    provider_root = provider_root.resolve()
    receipt = _load_json(receipt_path)
    if receipt.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise FormalProviderCacheError("provider cache receipt schema mismatch")
    if receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
        raise FormalProviderCacheError("provider cache receipt crossed research boundary")
    if receipt.get("contract_sha256") != contract.get("contract_sha256"):
        raise FormalProviderCacheError("provider cache contract hash mismatch")
    market = str(contract["market"])
    csv_index = _index_tree(provider_root / "data" / "csv_source")
    qlib_index = _index_tree(
        provider_root / "data" / "providers" / market,
        raw_subtree="features",
    )
    manifest_path, publication_path, manifest, publication = _validate_manifest(
        provider_root,
        contract,
        csv_index=csv_index,
        qlib_index=qlib_index,
    )
    if _sha256_file(manifest_path) != receipt.get("provider_manifest_sha256"):
        raise FormalProviderCacheError("provider cache manifest hash mismatch")
    if _sha256_file(publication_path) != receipt.get("publication_manifest_sha256"):
        raise FormalProviderCacheError("provider cache publication manifest hash mismatch")
    if publication.get("publication_identity_sha256") != receipt.get(
        "publication_identity_sha256"
    ):
        raise FormalProviderCacheError("provider publication identity hash mismatch")
    if str(manifest.get("provider_identity_sha256", "")) != str(
        receipt.get("provider_identity_sha256", "")
    ):
        raise FormalProviderCacheError("provider identity hash mismatch")
    expected = {
        "csv_tree_sha256": csv_index.identity_sha256,
        "csv_file_count": csv_index.file_count,
        "qlib_tree_sha256": qlib_index.identity_sha256,
        "qlib_file_count": qlib_index.file_count,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise FormalProviderCacheError(f"provider cache {key} mismatch")
    return receipt


def load_contract(path: Path) -> dict[str, Any]:
    contract = _load_json(path)
    expected = str(contract.pop("contract_sha256", ""))
    actual = _sha256_bytes(_canonical_json(contract))
    contract["contract_sha256"] = expected
    if expected != actual:
        raise FormalProviderCacheError("provider cache contract self-hash mismatch")
    return contract


def write_contract(path: Path, contract: Mapping[str, Any]) -> None:
    _write_json(path, contract)
