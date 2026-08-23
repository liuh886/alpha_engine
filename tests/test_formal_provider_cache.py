from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from src.artifacts.formal_provider_cache import (
    FormalProviderCacheError,
    build_provider_cache_contract,
    cache_key,
    seal_provider_cache,
    verify_provider_cache,
)
from src.data.market_provider import write_provider_manifest
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    write_selected_pool_price_publication_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_tree_identity(root: Path) -> tuple[str, int]:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    encoded = (
        json.dumps(
            {"records": records},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(records)


def _contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.1.0",
        "evidence_type": "formal_provider_cache_contract",
        "market": "us",
        "start": "2021-01-01",
        "requested_cutoff": "2026-08-07",
        "refresh_mode": "incremental_from_governed_seed",
        "max_rounds": 3,
        "auxiliary_symbols": ["QQQI", "TQQQ", "SGOV", "TYGO"],
        "inputs": {"contract.py": "a" * 64},
        "research_only": True,
        "trade_ready": False,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    payload["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _provider_contract() -> dict[str, object]:
    return {
        "amount_unit": "synthetic_close_times_volume",
        "available": True,
        "corporate_actions": True,
        "credential_env": None,
        "credentialed": False,
        "independent_group": "yahoo_finance",
        "markets": ["cn", "hk", "us"],
        "name": "yfinance",
        "price_mode": "provider_adjusted",
        "research_only": True,
        "source_family": "yahoo_finance",
        "trade_calendar": False,
        "usage_note": "research source",
        "volume_unit": "shares",
    }


def _provider_tree(tmp_path: Path) -> Path:
    root = tmp_path / "provider-us"
    csv_path = root / "data/csv_source/AAA.csv"
    qlib_root = root / "data/providers/us"
    qlib_path = qlib_root / "features/aaa/day/close.day.bin"
    qlib_volume_path = qlib_root / "features/aaa/day/volume.day.bin"
    calendar_path = qlib_root / "calendars/day.txt"
    instruments_path = qlib_root / "instruments/us.txt"
    csv_path.parent.mkdir(parents=True)
    qlib_path.parent.mkdir(parents=True)
    calendar_path.parent.mkdir(parents=True)
    instruments_path.parent.mkdir(parents=True)
    csv_path.write_text("date,close\n2026-08-07,10\n", encoding="utf-8")
    qlib_path.write_bytes(b"verified qlib bytes")
    qlib_volume_path.write_bytes(b"verified qlib volume bytes")
    calendar_path.write_text("2026-08-07\n", encoding="utf-8")
    instruments_path.write_text("AAA\t2026-08-07\t2026-08-07\n", encoding="utf-8")
    provider = write_provider_manifest(
        qlib_root,
        market="us",
        source_csv_files=[csv_path],
        cutoff="2026-08-07",
    )
    contract = _provider_contract()
    manifest = {
        "after": {"AAA": "2026-08-07"},
        "all_sources_current": True,
        "all_sources_ready": True,
        "auxiliary_symbols": [],
        "before": {"AAA": None},
        "benchmark": "AAA",
        "candidate_count": 1,
        "candidate_symbols": ["AAA"],
        "comparison_reference_symbols": [],
        "cutoff": "2026-08-07",
        "evidence_type": "selected_pool_price_refresh_v1",
        "failed_symbols": [],
        "failure_count": 0,
        "formal_auxiliary_fallback_symbols": [],
        "identity_contracts": {},
        "legacy_copied_symbols": [],
        "lifecycle_declared_terminal_symbols": [],
        "market": "us",
        "pool_id": "us_selected_equities_v2",
        "promotion_blocker": None,
        "promotion_eligible": True,
        "provider_architecture": {
            "formal_auxiliary_boundary": "governed fallback",
            "health": {},
            "independent_provider_order": ["yfinance"],
            "provider_order": ["yfinance"],
            "providers": {"yfinance": copy.deepcopy(contract)},
            "public_source_boundary": "research source",
            "same_source_warning": "none",
            "schema_version": "1.2",
            "selection_mode": "credential_aware_fallback",
        },
        "provider_identity_sha256": provider["provider_identity_sha256"],
        "quarantined_symbols": [],
        "records": [
            {
                "action": "fetched_incremental_update",
                "attempts": [
                    {
                        "error": None,
                        "ok": True,
                        "provider": "yfinance",
                        "provider_contract": copy.deepcopy(contract),
                        "provider_symbol": "AAA",
                        "round": 1,
                        "rows": 1,
                        "schema_errors": [],
                    }
                ],
                "first_date": "2026-08-07",
                "identity_contract": None,
                "last_date": "2026-08-07",
                "output_sha256": _sha256(csv_path),
                "promotion_status": "source_semantics_recorded",
                "provider": "yfinance",
                "provider_contract": copy.deepcopy(contract),
                "provider_symbol": "AAA",
                "rows": 1,
                "symbol": "AAA",
            }
        ],
        "refresh_mode": "incremental",
        "research_only": True,
        "schema_version": "1.2",
        "selected_providers": {"AAA": "yfinance"},
        "stale_symbols": [],
        "start": "2021-01-01",
        "status": "selected_pool_price_refresh_ready",
        "target_count": 1,
        "targets": ["AAA"],
        "terminal_history_symbols": [],
        "terminal_listing_evidence": {},
        "trade_ready": False,
        "unresolved_stale_symbols": [],
    }
    manifest_path = root / "artifacts/selected_pool_price_refresh_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    write_selected_pool_price_publication_manifest(
        root / "artifacts" / PUBLICATION_MANIFEST_NAME, manifest
    )
    return root


def test_provider_cache_contract_binds_market_code_pool_and_cutoff() -> None:
    contract = build_provider_cache_contract(
        repository_root=Path.cwd(), market="us", start="2021-01-01", requested_cutoff="2026-08-07"
    )
    inputs = contract["inputs"]
    assert isinstance(inputs, dict)
    for path in (
        "configs/research_universes/us_selected_equities_v2.yaml",
        "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml",
        "configs/pools/selected_pool_registry_v1.yaml",
        "scripts/data/refresh_selected_pool_prices.py",
        "scripts/data/refresh_selected_pool_prices_v2.py",
        "scripts/build_market_providers.py",
        "src/artifacts/formal_provider_cache.py",
        "src/data/adapters/yfinance_adapter.py",
        "src/data/market_provider.py",
        "src/data/provider_catalog.py",
        "src/data/router.py",
        "src/data/selected_pool_price_publication.py",
        "src/data/symbol_identity.py",
        "src/data/validation/schema.py",
    ):
        assert path in inputs
    assert "src/data/model_data_bundle.py" not in inputs
    assert contract["refresh_mode"] == "incremental_from_governed_seed"
    assert cache_key(contract).startswith("formal-provider-1.1.0-us-2026-08-07-")


def test_governed_terminal_history_uses_stable_line_endings() -> None:
    attributes = (Path.cwd() / ".gitattributes").read_text(encoding="utf-8")
    assert "data/csv_clean/EA.csv text eol=lf" in attributes


def test_sealed_provider_cache_binds_raw_publication_csv_and_qlib_bytes(tmp_path: Path) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    sealed = seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)
    assert sealed["candidate_count"] == 1
    assert len(sealed["publication_manifest_sha256"]) == 64
    assert len(sealed["publication_identity_sha256"]) == 64
    assert verify_provider_cache(
        provider_root=root, contract=contract, receipt_path=receipt
    ) == sealed

    qlib_path = root / "data/providers/us/features/aaa/day/close.day.bin"
    qlib_path.write_bytes(b"tampered")
    with pytest.raises(FormalProviderCacheError, match="feature-tree hash mismatch"):
        verify_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)


def test_provider_cache_keeps_legacy_tree_receipt_identity(tmp_path: Path) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    sealed = seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)

    csv_digest, csv_count = _legacy_tree_identity(root / "data/csv_source")
    qlib_digest, qlib_count = _legacy_tree_identity(root / "data/providers/us")
    assert sealed["csv_tree_sha256"] == csv_digest
    assert sealed["csv_file_count"] == csv_count
    assert sealed["qlib_tree_sha256"] == qlib_digest
    assert sealed["qlib_file_count"] == qlib_count


@pytest.mark.parametrize("operation", ("seal", "verify"))
def test_provider_cache_hashes_each_provider_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    if operation == "verify":
        seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)

    csv_path = (root / "data/csv_source/AAA.csv").resolve()
    feature_paths = {
        path.resolve()
        for path in (root / "data/providers/us/features").rglob("*")
        if path.is_file()
    }
    tracked_paths = {csv_path, *feature_paths}
    read_counts: Counter[Path] = Counter()
    original_open = Path.open

    def counted_open(path: Path, *args: object, **kwargs: object):
        mode = str(args[0]) if args else str(kwargs.get("mode", "r"))
        resolved = path.resolve()
        if resolved in tracked_paths and "r" in mode:
            read_counts[resolved] += 1
        return original_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", counted_open)
    if operation == "seal":
        seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)
    else:
        verify_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)

    assert read_counts[csv_path] == 1
    assert {read_counts[path] for path in feature_paths} == {1}


@pytest.mark.parametrize("failure", ("missing", "tampered", "projection"))
def test_provider_cache_rejects_invalid_publication(tmp_path: Path, failure: str) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)
    publication = root / "artifacts" / PUBLICATION_MANIFEST_NAME
    if failure == "missing":
        publication.unlink()
    elif failure == "tampered":
        publication.write_text("{}", encoding="utf-8")
    else:
        manifest_path = root / "artifacts/selected_pool_price_refresh_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["records"][0]["provider_symbol"] = "CHANGED"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FormalProviderCacheError, match="provider evidence is invalid"):
        verify_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)


def test_provider_cache_rejects_contract_or_research_boundary_drift(tmp_path: Path) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    seal_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)
    changed = copy.deepcopy(contract)
    changed["contract_sha256"] = "c" * 64
    with pytest.raises(FormalProviderCacheError, match="contract hash mismatch"):
        verify_provider_cache(provider_root=root, contract=changed, receipt_path=receipt)

    manifest_path = root / "artifacts/selected_pool_price_refresh_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trade_ready"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FormalProviderCacheError, match="research boundary"):
        verify_provider_cache(provider_root=root, contract=contract, receipt_path=receipt)
