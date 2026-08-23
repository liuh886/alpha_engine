from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.selected_pool_price_fixtures import selected_pool_price_source
from src.data.selected_pool_price_publication import (
    SelectedPoolPricePublicationError,
    build_selected_pool_price_publication_manifest,
    load_selected_pool_price_publication_manifest,
    verify_selected_pool_price_publication_manifest,
    write_selected_pool_price_publication_manifest,
)


def _source(market: str = "cn") -> dict[str, object]:
    return selected_pool_price_source(market)


def _last_record(source: dict[str, object]) -> dict[str, object]:
    records = source["records"]
    assert isinstance(records, list)
    record = records[-1]
    assert isinstance(record, dict)
    return record


def _rewrite_publication(path: Path, payload: dict[str, object]) -> None:
    identity = dict(payload)
    identity.pop("publication_identity_sha256", None)
    encoded = (json.dumps(identity, sort_keys=True, separators=(",", ":")) + "\n").encode()
    payload["publication_identity_sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _tigo_source() -> dict[str, object]:
    source = _source("us")
    source["candidate_symbols"][0] = "TIGO"
    source["benchmark"] = "TIGO"
    source["selected_providers"] = {"TIGO": "yfinance"}
    contract = {
        "expected_provider_symbol": "TIGO",
        "expected_issuer": "Millicom International Cellular S.A.",
        "forbidden_substitute": "TYGO",
    }
    source["records"][0].update(
        symbol="TIGO", provider_symbol="TIGO", identity_contract=copy.deepcopy(contract)
    )
    source["identity_contracts"] = {"TIGO": contract}
    return source


def _change_attempt_diagnostics(source: dict[str, object]) -> None:
    record = _last_record(source)
    attempts = record["attempts"]
    assert isinstance(attempts, list)
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    attempt.update(error="different transport failure", round=99, circuit_breaker_open=True)
    attempts.insert(0, copy.deepcopy(attempt))


def _change_action(source: dict[str, object]) -> None:
    _last_record(source)["action"] = "fetched_full_refresh"


def _change_health(source: dict[str, object]) -> None:
    architecture = source["provider_architecture"]
    assert isinstance(architecture, dict)
    architecture["health"] = {"different": "runtime state"}


def _change_unused_provider_docs(source: dict[str, object]) -> None:
    architecture = source["provider_architecture"]
    assert isinstance(architecture, dict)
    providers = architecture["providers"]
    assert isinstance(providers, dict)
    contract = providers["efinance"]
    assert isinstance(contract, dict)
    contract.update(available=False, credential_env="CHANGED", usage_note="changed docs")


def _change_selected_provider_docs(source: dict[str, object]) -> None:
    architecture = source["provider_architecture"]
    assert isinstance(architecture, dict)
    providers = architecture["providers"]
    assert isinstance(providers, dict)
    contract = providers["akshare_sina"]
    assert isinstance(contract, dict)
    contract["usage_note"] = "changed docs"
    for record in source["records"]:
        if isinstance(record, dict) and record.get("provider") == "akshare_sina":
            record_contract = record["provider_contract"]
            assert isinstance(record_contract, dict)
            record_contract["usage_note"] = "changed docs"


@pytest.mark.parametrize(
    "mutate",
    (
        _change_attempt_diagnostics,
        _change_action,
        _change_health,
        _change_unused_provider_docs,
        _change_selected_provider_docs,
    ),
)
def test_operational_diagnostics_do_not_change_publication_identity(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    source = _source()
    changed = copy.deepcopy(source)
    mutate(changed)

    assert build_selected_pool_price_publication_manifest(source) == (
        build_selected_pool_price_publication_manifest(changed)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (("output_sha256", "0" * 64), ("provider_symbol", "different-provider-symbol")),
)
def test_governed_record_change_changes_publication_identity(field: str, value: str) -> None:
    source = _source()
    changed = copy.deepcopy(source)
    records = changed["records"]
    assert isinstance(records, list) and isinstance(records[0], dict)
    records[0][field] = value

    first = build_selected_pool_price_publication_manifest(source)
    second = build_selected_pool_price_publication_manifest(changed)

    assert first["publication_identity_sha256"] != second["publication_identity_sha256"]


def test_selected_semantic_contract_change_changes_identity() -> None:
    source = _source()
    changed = copy.deepcopy(source)
    architecture = changed["provider_architecture"]
    assert isinstance(architecture, dict)
    contract = architecture["providers"]["akshare_sina"]
    contract["price_mode"] = "different_adjustment"
    for record in changed["records"]:
        if isinstance(record, dict) and record.get("provider") == "akshare_sina":
            record["provider_contract"]["price_mode"] = "different_adjustment"

    first = build_selected_pool_price_publication_manifest(source)
    second = build_selected_pool_price_publication_manifest(changed)

    assert first["publication_identity_sha256"] != second["publication_identity_sha256"]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("promotion_eligible", False),
        ("all_sources_ready", False),
        ("quarantined_symbols", ["000001"]),
        ("legacy_copied_symbols", ["000001"]),
        ("unresolved_stale_symbols", ["000001"]),
        ("failed_symbols", ["000001"]),
    ),
)
def test_inconsistent_promotion_gate_fails_closed(field: str, value: object) -> None:
    source = _source()
    source[field] = value

    with pytest.raises(SelectedPoolPricePublicationError, match="not publication ready"):
        build_selected_pool_price_publication_manifest(source)


def test_selected_provider_mapping_mismatch_fails_closed() -> None:
    source = _source()
    selected = source["selected_providers"]
    assert isinstance(selected, dict)
    selected["000001"] = "different_provider"

    with pytest.raises(SelectedPoolPricePublicationError, match="mapping is inconsistent"):
        build_selected_pool_price_publication_manifest(source)


def test_cn_yahoo_source_without_formal_auxiliary_proof_fails_closed() -> None:
    source = _source()
    record = next(
        item for item in source["records"] if isinstance(item, dict) and item["symbol"] == "515180"
    )
    architecture = source["provider_architecture"]
    contract = architecture["providers"]["yfinance"]
    record.update(
        provider="yfinance",
        provider_contract=copy.deepcopy(contract),
        provider_symbol="515180.SS",
    )
    source["selected_providers"]["515180"] = "yfinance"

    with pytest.raises(SelectedPoolPricePublicationError, match="not an authorized"):
        build_selected_pool_price_publication_manifest(source)


def test_terminal_history_contract_mismatch_fails_closed() -> None:
    source = _source("us")
    record = next(
        item for item in source["records"] if isinstance(item, dict) and item["symbol"] == "EA"
    )
    record["source_sha256"] = "0" * 64

    with pytest.raises(SelectedPoolPricePublicationError, match="lifecycle contract"):
        build_selected_pool_price_publication_manifest(source)


def test_terminal_reference_order_is_stable_but_membership_is_semantic() -> None:
    source = _source("us")
    reordered = copy.deepcopy(source)
    reordered["records"][-1]["terminal_lifecycle"]["public_references"].reverse()
    assert build_selected_pool_price_publication_manifest(source) == (
        build_selected_pool_price_publication_manifest(reordered)
    )

    changed = copy.deepcopy(source)
    changed["records"][-1]["terminal_lifecycle"]["public_references"].append(
        "https://example.test/new-authority"
    )
    first = build_selected_pool_price_publication_manifest(source)
    second = build_selected_pool_price_publication_manifest(changed)
    assert first["publication_identity_sha256"] != second["publication_identity_sha256"]


def test_authoritative_provider_symbol_contract_cannot_be_rewritten() -> None:
    source = _tigo_source()
    record = source["records"][0]
    build_selected_pool_price_publication_manifest(source)

    malicious = {
        "expected_provider_symbol": "TYGO",
        "expected_issuer": "different issuer",
        "forbidden_substitute": "TIGO",
    }
    record["provider_symbol"] = "TYGO"
    record["identity_contract"] = malicious
    source["identity_contracts"] = {"TIGO": copy.deepcopy(malicious)}
    with pytest.raises(SelectedPoolPricePublicationError, match="identity contracts"):
        build_selected_pool_price_publication_manifest(source)


def test_rehashed_publication_cannot_rewrite_authoritative_provider_symbol(
    tmp_path: Path,
) -> None:
    target = tmp_path / "publication.json"
    write_selected_pool_price_publication_manifest(target, _tigo_source())
    payload = json.loads(target.read_text(encoding="utf-8"))
    malicious = {
        "expected_provider_symbol": "TYGO",
        "expected_issuer": "different issuer",
        "forbidden_substitute": "TIGO",
    }
    for record in payload["records"]:
        if record["symbol"] == "TIGO":
            record["provider_symbol"] = "TYGO"
            record["identity_contract"] = copy.deepcopy(malicious)
    payload["identity_contracts"] = {"TIGO": malicious}
    _rewrite_publication(target, payload)

    with pytest.raises(SelectedPoolPricePublicationError, match="identity contracts"):
        load_selected_pool_price_publication_manifest(target)


def test_formal_yahoo_fallback_emits_normalized_proof_and_requires_all_failures() -> None:
    source = _source()
    record = next(
        item for item in source["records"] if isinstance(item, dict) and item["symbol"] == "515180"
    )
    architecture = source["provider_architecture"]
    yfinance_contract = architecture["providers"]["yfinance"]
    record.update(
        action="fetched_full_refresh",
        provider="yfinance",
        provider_contract=copy.deepcopy(yfinance_contract),
        provider_symbol="515180.SS",
        promotion_status="formal_auxiliary_governed_yahoo_fallback",
    )
    for attempt in record["attempts"]:
        if attempt.get("provider") == "tencent_qfq_history":
            attempt.update(ok=False, error="transient Tencent failure")
    record["attempts"].append(
        {
            "error": None,
            "ok": True,
            "provider": "yfinance",
            "provider_contract": copy.deepcopy(yfinance_contract),
            "provider_symbol": "515180.SS",
            "round": 2,
            "rows": 2,
            "schema_errors": [],
        }
    )
    source["selected_providers"]["515180"] = "yfinance"
    source["formal_auxiliary_fallback_symbols"] = ["515180"]

    publication = build_selected_pool_price_publication_manifest(source)
    proof = publication["provider_architecture"]["formal_auxiliary_fallback_authorizations"][0]
    assert proof == {
        "failed_preferred_providers": [
            "akshare", "akshare_sina", "baostock", "efinance", "tencent_qfq_history"
        ],
        "selected_provider": "yfinance",
        "symbol": "515180",
    }

    record["attempts"] = [
        attempt for attempt in record["attempts"] if attempt.get("provider") != "akshare"
    ]
    with pytest.raises(SelectedPoolPricePublicationError, match="lacks failed proof for akshare"):
        build_selected_pool_price_publication_manifest(source)


def test_unknown_source_field_fails_closed() -> None:
    source = _source()
    source["new_unclassified_field"] = True

    with pytest.raises(SelectedPoolPricePublicationError, match="unsupported source"):
        build_selected_pool_price_publication_manifest(source)


@pytest.mark.parametrize("mutation", ("missing_date", "provider_map", "quarantine"))
def test_rehashed_publication_tamper_still_fails_cross_invariants(
    tmp_path: Path, mutation: str
) -> None:
    target = tmp_path / "publication.json"
    write_selected_pool_price_publication_manifest(target, _source())
    payload = json.loads(target.read_text(encoding="utf-8"))
    if mutation == "missing_date":
        payload["records"][0].pop("first_date")
    elif mutation == "provider_map":
        payload["selected_providers"]["000001"] = "different_provider"
    else:
        payload["quarantined_symbols"] = ["000001"]
    _rewrite_publication(target, payload)

    with pytest.raises(SelectedPoolPricePublicationError):
        load_selected_pool_price_publication_manifest(target)


def test_publication_manifest_is_smaller_self_verified_evidence(tmp_path: Path) -> None:
    for market in ("us", "cn"):
        source = _source(market)
        target = tmp_path / market / "publication.json"
        projected = write_selected_pool_price_publication_manifest(target, source)

        assert load_selected_pool_price_publication_manifest(target) == projected
        assert verify_selected_pool_price_publication_manifest(target, source) == projected
        assert target.stat().st_size < len(json.dumps(source).encode())

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["records"][0]["output_sha256"] = "0" * 64
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SelectedPoolPricePublicationError, match="identity mismatch"):
        load_selected_pool_price_publication_manifest(target)
