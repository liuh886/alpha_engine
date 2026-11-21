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


@pytest.mark.parametrize("value", ("true", 1, None, {}))
def test_cutoff_attempt_diagnostic_requires_a_boolean(value: object) -> None:
    source = _source()
    source["records"][0]["attempts"][0]["requested_end_present"] = value

    with pytest.raises(SelectedPoolPricePublicationError, match="cutoff outcome is invalid"):
        build_selected_pool_price_publication_manifest(source)


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


def test_unresolved_stale_symbols_are_named_in_publication_error() -> None:
    source = _source()
    source["promotion_eligible"] = False
    source["unresolved_stale_symbols"] = ["CRCL", "TEM"]
    source["promotion_blocker"] = (
        "stale selected-pool sources without an explicit lifecycle declaration"
    )

    with pytest.raises(SelectedPoolPricePublicationError) as caught:
        build_selected_pool_price_publication_manifest(source)

    message = str(caught.value)
    assert "unresolved_stale_symbols=CRCL,TEM" in message
    assert "promotion_blocker=stale selected-pool sources" in message


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


@pytest.mark.parametrize("mutation", ("listing_date", "lifecycle_market"))
def test_terminal_listing_and_record_lifecycle_must_agree(mutation: str) -> None:
    source = _source("us")
    if mutation == "listing_date":
        source["terminal_listing_evidence"]["EA"]["terminal_date"] = "2026-08-03"
    else:
        source["records"][-1]["terminal_lifecycle"]["market"] = "cn"

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


def test_rehashed_publication_cannot_split_terminal_listing_evidence(
    tmp_path: Path,
) -> None:
    target = tmp_path / "publication.json"
    write_selected_pool_price_publication_manifest(target, _source("us"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["terminal_listing_evidence"]["EA"]["terminal_date"] = "2026-08-03"
    _rewrite_publication(target, payload)

    with pytest.raises(SelectedPoolPricePublicationError, match="terminal lifecycle"):
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


def _vix_gap(**overrides: object) -> dict[str, object]:
    gap: dict[str, object] = {
        "attempted_providers": ["cboe_public"],
        "market": "us",
        "reason": "CBOE source unavailable in the fixture",
        "role": "optional_reference",
        "status": "missing",
        "symbol": "VIX",
    }
    gap.update(overrides)
    return gap


def test_optional_auxiliary_gap_is_scoped_and_self_verified(tmp_path: Path) -> None:
    source = _source("us")
    source["optional_auxiliary_gaps"] = [_vix_gap()]

    projected = build_selected_pool_price_publication_manifest(source)
    assert projected["optional_auxiliary_gaps"] == [_vix_gap()]
    assert "VIX" not in {record["symbol"] for record in projected["records"]}

    target = tmp_path / "publication.json"
    write_selected_pool_price_publication_manifest(target, source)
    assert load_selected_pool_price_publication_manifest(target) == projected

    without_gap = _source("us")
    assert build_selected_pool_price_publication_manifest(without_gap)[
        "publication_identity_sha256"
    ] != projected["publication_identity_sha256"]


def test_optional_auxiliary_gap_only_accepts_declared_optional_references() -> None:
    source = _source("us")
    source["optional_auxiliary_gaps"] = [_vix_gap(symbol="QQQI")]
    with pytest.raises(SelectedPoolPricePublicationError, match="gap is invalid"):
        build_selected_pool_price_publication_manifest(source)

    source = _source("us")
    source["optional_auxiliary_gaps"] = [_vix_gap(symbol="AAA")]
    with pytest.raises(SelectedPoolPricePublicationError, match="gap is invalid"):
        build_selected_pool_price_publication_manifest(source)


def test_optional_auxiliary_gap_rejects_malformed_or_noncanonical_rows() -> None:
    source = _source("us")
    source["optional_auxiliary_gaps"] = [_vix_gap(reason="")]
    with pytest.raises(SelectedPoolPricePublicationError, match="gap is invalid"):
        build_selected_pool_price_publication_manifest(source)

    source = _source("us")
    source["optional_auxiliary_gaps"] = [
        _vix_gap(attempted_providers=["yfinance", "cboe_public"])
    ]
    with pytest.raises(SelectedPoolPricePublicationError, match="not canonical"):
        build_selected_pool_price_publication_manifest(source)

    source = _source("us")
    source["optional_auxiliary_gaps"] = [_vix_gap(), _vix_gap()]
    with pytest.raises(SelectedPoolPricePublicationError, match="gap is invalid"):
        build_selected_pool_price_publication_manifest(source)


def test_rehashed_publication_cannot_invent_an_optional_gap(tmp_path: Path) -> None:
    path = tmp_path / "publication.json"
    write_selected_pool_price_publication_manifest(path, _source("us"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["optional_auxiliary_gaps"] = [_vix_gap(symbol="QQQI")]
    _rewrite_publication(path, payload)
    with pytest.raises(SelectedPoolPricePublicationError, match="gap is invalid"):
        load_selected_pool_price_publication_manifest(path)


def _source_provenance() -> dict[str, object]:
    return {
        "provider": "cboe_public",
        "provider_symbol": "VIX",
        "source_url": (
            "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/"
            "VIX_History.csv"
        ),
        "response_sha256": "a" * 64,
        "response_bytes": 1234,
        "fetched_at_utc": "2026-11-17T12:30:00+00:00",
        "source_schema": "cboe_vix_history_csv_v1",
        "source_date_format": "%m/%d/%Y",
        "price_basis": "index_level_unadjusted",
        "volume_basis": "not_applicable_index",
        "amount_basis": "not_applicable_index",
        "requested_start": "2021-01-01",
        "requested_end": "2026-11-16",
        "first_date": "2021-01-04",
        "last_date": "2026-11-16",
        "rows": 1508,
        "terms_caveat": "CBOE compiled-for-convenience caveat",
        "research_only": True,
        "trade_ready": False,
    }


def test_source_provenance_is_retained_and_bound_into_publication_identity() -> None:
    source = _source("us")
    record = source["records"][0]
    assert isinstance(record, dict)
    record["source_provenance"] = _source_provenance()

    publication = build_selected_pool_price_publication_manifest(source)
    published = next(
        row for row in publication["records"] if row["symbol"] == record["symbol"]
    )
    assert published["source_provenance"] == _source_provenance()

    baseline = build_selected_pool_price_publication_manifest(_source("us"))
    assert publication["publication_identity_sha256"] != baseline[
        "publication_identity_sha256"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("response_sha256", "not-a-hash"),
        ("source_url", "file:///local/vix.csv"),
        ("fetched_at_utc", ""),
        ("provider", ""),
        ("trade_ready", True),
    ),
)
def test_source_provenance_must_be_complete_and_research_bound(field: str, value: object) -> None:
    source = _source("us")
    record = source["records"][0]
    assert isinstance(record, dict)
    provenance = _source_provenance()
    provenance[field] = value
    record["source_provenance"] = provenance

    with pytest.raises(SelectedPoolPricePublicationError, match="provenance"):
        build_selected_pool_price_publication_manifest(source)


def _fund_provenance(provider: str = "akshare_sina_fund") -> dict[str, object]:
    return {
        "provider": provider,
        "provider_symbol": "sh515180",
        "source_url": (
            "https://finance.sina.com.cn/realstock/company/sh515180/"
            "hisdata_klc2/klc_kl.js"
        ),
        "response_sha256": "a" * 64,
        "response_bytes": 4321,
        "fetched_at_utc": "2026-11-21T08:00:00+00:00",
        "source_schema": "date,open,high,low,close,volume,amount,postVol,postAmt",
        "source_date_format": "date",
        "price_basis": "provider_reported_raw",
        "volume_basis": "withheld_sina_reported_shares",
        "amount_basis": "withheld_vendor_reported_cny_not_mixed",
        "requested_start": "2026-11-20",
        "requested_end": "2026-11-21",
        "first_date": "2026-11-20",
        "last_date": "2026-11-21",
        "rows": 2,
        "terms_caveat": "Volume and amount withheld: Sina shares/CNY do not match the governed lot basis.",
        "research_only": True,
        "trade_ready": False,
    }


def _with_sina_fund_record(source: dict[str, object]) -> dict[str, object]:
    from src.data.provider_catalog import provider_manifest_entry

    record = _last_record(source)
    record["provider"] = "akshare_sina_fund"
    record["provider_symbol"] = "sh515180"
    record["provider_contract"] = provider_manifest_entry("akshare_sina_fund")
    record["source_provenance"] = _fund_provenance()
    records = source["records"]
    assert isinstance(records, list)
    for attempt in record["attempts"]:
        attempt["provider"] = "akshare_sina_fund"
        attempt["ok"] = True
        attempt["provider_symbol"] = "sh515180"
    selected = source["selected_providers"]
    assert isinstance(selected, dict)
    selected["515180"] = "akshare_sina_fund"
    architecture = source["provider_architecture"]
    assert isinstance(architecture, dict)
    architecture["provider_order"].append("akshare_sina_fund")
    architecture["providers"]["akshare_sina_fund"] = provider_manifest_entry(
        "akshare_sina_fund"
    )
    return source


def test_sina_fund_fallback_is_publication_ready_with_withheld_volume_basis() -> None:
    source = _with_sina_fund_record(_source("cn"))

    publication = build_selected_pool_price_publication_manifest(source)

    assert publication["selected_providers"]["515180"] == "akshare_sina_fund"
    record = next(
        row for row in publication["records"] if row["symbol"] == "515180"
    )
    assert record["source_provenance"]["volume_basis"] == (
        "withheld_sina_reported_shares"
    )
    assert record["source_provenance"]["price_basis"] == "provider_reported_raw"
    # The withheld basis is a declared provider contract, not an unknown side channel.
    contract = publication["provider_architecture"]["selected_provider_contracts"][
        "akshare_sina_fund"
    ]
    assert contract["volume_unit"] == "withheld_vendor_basis_conflict"
    assert contract["price_mode"] == "raw_unadjusted"


def test_source_provenance_accepts_bounded_retry_evidence() -> None:
    from src.data.provider_catalog import provider_manifest_entry

    source = _source("cn")
    record = _last_record(source)
    contract = provider_manifest_entry("akshare")
    record["provider"] = "akshare"
    record["provider_contract"] = contract
    architecture = source["provider_architecture"]
    assert isinstance(architecture, dict)
    architecture["providers"]["akshare"] = contract
    provenance = _fund_provenance("akshare")
    provenance["retry_attempts"] = 3
    provenance["retry_outcome"] = "succeeded_after_retry"
    provenance["retry_history"] = [
        {"attempt": 1, "error_class": "provider_unavailable", "retryable": True},
        {"attempt": 2, "error_class": "provider_unavailable", "retryable": True},
    ]
    provenance["retry_policy"] = {"max_attempts": 3, "max_honored_retry_after_seconds": 30.0}
    record["source_provenance"] = provenance
    selected = source["selected_providers"]
    assert isinstance(selected, dict)
    # The fixture already declares akshare in the provider architecture.
    selected["515180"] = "akshare"

    publication = build_selected_pool_price_publication_manifest(source)

    published = next(
        row for row in publication["records"] if row["symbol"] == "515180"
    )
    assert published["source_provenance"]["retry_attempts"] == 3
    assert published["source_provenance"]["retry_outcome"] == "succeeded_after_retry"


def test_source_provenance_still_rejects_unknown_keys() -> None:
    source = _source("us")
    record = source["records"][0]
    assert isinstance(record, dict)
    provenance = _source_provenance()
    provenance["fabricated_basis"] = "unknown"
    record["source_provenance"] = provenance

    with pytest.raises(SelectedPoolPricePublicationError, match="provenance"):
        build_selected_pool_price_publication_manifest(source)
