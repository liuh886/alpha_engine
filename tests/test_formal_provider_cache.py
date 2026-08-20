from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.artifacts.formal_provider_cache import (
    FormalProviderCacheError,
    build_provider_cache_contract,
    cache_key,
    seal_provider_cache,
    verify_provider_cache,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
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
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    payload["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _provider_tree(tmp_path: Path) -> Path:
    root = tmp_path / "provider-us"
    csv_path = root / "data/csv_source/AAA.csv"
    qlib_path = root / "data/providers/us/features/aaa/day/close.day.bin"
    csv_path.parent.mkdir(parents=True)
    qlib_path.parent.mkdir(parents=True)
    csv_path.write_text("date,close\n2026-08-07,10\n", encoding="utf-8")
    qlib_path.write_bytes(b"verified qlib bytes")
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": True,
        "pool_id": "us_selected_equities_v2",
        "start": "2021-01-01",
        "cutoff": "2026-08-07",
        "candidate_symbols": ["AAA"],
        "candidate_count": 1,
        "provider_identity_sha256": "b" * 64,
        "records": [
            {
                "symbol": "AAA",
                "output_sha256": _sha256(csv_path),
            }
        ],
        "research_only": True,
        "trade_ready": False,
    }
    manifest_path = root / "artifacts/selected_pool_price_refresh_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_provider_cache_contract_binds_market_code_pool_and_cutoff() -> None:
    contract = build_provider_cache_contract(
        repository_root=Path.cwd(),
        market="us",
        start="2021-01-01",
        requested_cutoff="2026-08-07",
    )
    inputs = contract["inputs"]
    assert isinstance(inputs, dict)
    assert "configs/research_universes/us_selected_equities_v2.yaml" in inputs
    assert "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml" in inputs
    assert "configs/pools/selected_pool_registry_v1.yaml" in inputs
    assert "scripts/data/refresh_selected_pool_prices_v2.py" in inputs
    assert "scripts/build_market_providers.py" in inputs
    assert "src/artifacts/formal_provider_cache.py" in inputs
    assert "src/data/adapters/yfinance_adapter.py" in inputs
    assert contract["refresh_mode"] == "incremental_from_governed_seed"
    assert cache_key(contract).startswith("formal-provider-1.0.0-us-2026-08-07-")


def test_governed_terminal_history_uses_stable_line_endings() -> None:
    attributes = (Path.cwd() / ".gitattributes").read_text(encoding="utf-8")
    assert "data/csv_clean/EA.csv text eol=lf" in attributes


def test_sealed_provider_cache_verifies_exact_manifest_csv_and_qlib_bytes(
    tmp_path: Path,
) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    sealed = seal_provider_cache(
        provider_root=root,
        contract=contract,
        receipt_path=receipt,
    )
    assert sealed["candidate_count"] == 1
    assert sealed["research_only"] is True
    assert sealed["trade_ready"] is False
    assert verify_provider_cache(
        provider_root=root,
        contract=contract,
        receipt_path=receipt,
    ) == sealed

    qlib_path = root / "data/providers/us/features/aaa/day/close.day.bin"
    qlib_path.write_bytes(b"tampered")
    with pytest.raises(FormalProviderCacheError, match="qlib_tree_sha256 mismatch"):
        verify_provider_cache(
            provider_root=root,
            contract=contract,
            receipt_path=receipt,
        )


def test_provider_cache_rejects_contract_or_research_boundary_drift(
    tmp_path: Path,
) -> None:
    root = _provider_tree(tmp_path)
    contract = _contract()
    receipt = root / "artifacts/formal-provider-cache-receipt.json"
    seal_provider_cache(
        provider_root=root,
        contract=contract,
        receipt_path=receipt,
    )
    changed = copy.deepcopy(contract)
    changed["contract_sha256"] = "c" * 64
    with pytest.raises(FormalProviderCacheError, match="contract hash mismatch"):
        verify_provider_cache(
            provider_root=root,
            contract=changed,
            receipt_path=receipt,
        )

    manifest_path = root / "artifacts/selected_pool_price_refresh_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trade_ready"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FormalProviderCacheError, match="research boundary"):
        verify_provider_cache(
            provider_root=root,
            contract=contract,
            receipt_path=receipt,
        )
