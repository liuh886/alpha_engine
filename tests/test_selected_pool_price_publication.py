from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from src.data.selected_pool_price_publication import (
    SelectedPoolPricePublicationError,
    build_selected_pool_price_publication_manifest,
    load_selected_pool_price_publication_manifest,
    verify_selected_pool_price_publication_manifest,
    write_selected_pool_price_publication_manifest,
)


def _source(market: str = "cn") -> dict[str, object]:
    path = Path(f"data/research/model_data_bundle_v1/components/{market}-selected-pool-prices.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _last_record(source: dict[str, object]) -> dict[str, object]:
    records = source["records"]
    assert isinstance(records, list)
    record = records[-1]
    assert isinstance(record, dict)
    return record


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


def test_publication_manifest_is_smaller_self_verified_evidence(tmp_path: Path) -> None:
    for market in ("us", "cn"):
        source = _source(market)
        target = tmp_path / market / "publication.json"
        projected = write_selected_pool_price_publication_manifest(target, source)

        assert load_selected_pool_price_publication_manifest(target) == projected
        assert verify_selected_pool_price_publication_manifest(target, source) == projected
        assert target.stat().st_size < len(json.dumps(source).encode()) // 2

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["records"][0]["output_sha256"] = "0" * 64
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SelectedPoolPricePublicationError, match="identity mismatch"):
        load_selected_pool_price_publication_manifest(target)
