"""Project selected-pool provider runs into stable publication evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from src.data.symbol_identity import (
    selected_pool_provider_identity_contract,
    validate_selected_pool_provider_identity,
)

SOURCE_SCHEMA = "1.2"
SOURCE_EVIDENCE_TYPE = "selected_pool_price_refresh_v1"
PUBLICATION_SCHEMA = "1.0.0"
PUBLICATION_EVIDENCE_TYPE = "selected_pool_price_publication_v1"
PUBLICATION_MANIFEST_NAME = "selected_pool_price_publication_manifest.json"

_SOURCE_KEYS = {
    "after", "all_sources_current", "all_sources_ready", "auxiliary_symbols",
    "before", "benchmark", "candidate_count", "candidate_symbols", "comparison_reference_symbols",
    "cutoff", "evidence_type", "failed_symbols", "failure_count",
    "formal_auxiliary_fallback_symbols", "identity_contracts", "legacy_copied_symbols",
    "lifecycle_declared_terminal_symbols", "market", "pool_id", "promotion_blocker",
    "promotion_eligible", "provider_architecture", "provider_identity_sha256",
    "quarantined_symbols", "records", "refresh_mode", "research_only", "schema_version",
    "selected_providers", "stale_symbols", "start", "status", "target_count", "targets",
    "terminal_history_symbols", "terminal_listing_evidence", "trade_ready",
    "unresolved_stale_symbols",
}
_OPERATIONAL_SOURCE_KEYS = {"after", "before", "refresh_mode", "target_count", "targets"}
_LIST_SOURCE_KEYS = {
    "auxiliary_symbols", "candidate_symbols", "comparison_reference_symbols", "failed_symbols",
    "formal_auxiliary_fallback_symbols", "legacy_copied_symbols",
    "lifecycle_declared_terminal_symbols", "quarantined_symbols", "stale_symbols",
    "terminal_history_symbols", "unresolved_stale_symbols",
}
_RECORD_KEYS = {
    "action", "attempts", "first_date", "identity_contract", "last_date", "output_sha256",
    "promotion_status", "provider", "provider_contract", "provider_symbol", "rows",
    "source_path", "source_sha256", "stale_reason", "symbol", "terminal_lifecycle",
}
_PUBLICATION_RECORD_FIELDS = _RECORD_KEYS - {"action", "attempts", "provider_contract"}
_ATTEMPT_KEYS = {
    "circuit_breaker_open", "cutoff_complete", "error", "first_date", "independent_group",
    "last_date", "observed_last_date", "ok", "provider", "provider_contract",
    "provider_symbol", "requested_cutoff", "round", "rows", "schema_errors", "source_family",
}
_ARCHITECTURE_KEYS = {
    "formal_auxiliary_boundary", "health", "independent_provider_order", "provider_order",
    "providers", "public_source_boundary", "same_source_warning", "schema_version", "selection_mode",
}
_PROVIDER_CONTRACT_KEYS = {
    "amount_unit", "available", "corporate_actions", "credential_env", "credentialed",
    "independent_group", "markets", "name", "price_mode", "research_only", "source_family",
    "trade_calendar", "usage_note", "volume_unit",
}
_SEMANTIC_PROVIDER_CONTRACT_KEYS = _PROVIDER_CONTRACT_KEYS - {
    "available", "credential_env", "usage_note",
}
_PUBLICATION_ARCHITECTURE_KEYS = {
    "formal_auxiliary_fallback_authorizations", "schema_version",
    "selected_provider_contracts", "selection_mode",
}
_FALLBACK_AUTHORIZATION_KEYS = {
    "failed_preferred_providers", "selected_provider", "symbol",
}
_TERMINAL_LIFECYCLE_KEYS = {
    "active_universe_after_terminal_date_allowed", "event_type", "governed_history_path",
    "governed_history_sha256", "historical_rows_retained", "market", "public_references",
    "reason", "suspension_effective_date", "terminal_date",
}
_TERMINAL_LISTING_KEYS = {"event_type", "reason", "terminal_date"}
_DIAGNOSTICS_POLICY = {
    "excluded_operational_record_fields": ["action", "attempts", "provider_contract"],
    "excluded_top_level_fields": sorted(_OPERATIONAL_SOURCE_KEYS),
    "excluded_unused_provider_fields": [
        "available", "credential_env", "health", "provider_order", "usage_note",
    ],
    "full_diagnostics_retained_in_run_artifact": True,
}
_PUBLICATION_KEYS = (_SOURCE_KEYS - _OPERATIONAL_SOURCE_KEYS) | {
    "diagnostics_policy", "publication_identity_sha256", "source_evidence_type",
    "source_schema_version",
}


class SelectedPoolPricePublicationError(ValueError):
    """Raised when provider evidence cannot be safely projected."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SelectedPoolPricePublicationError(
            f"unsupported {label} fields: missing={sorted(expected - set(value))} "
            f"unknown={sorted(set(value) - expected)}"
        )


def _assert_known_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    if unknown:
        raise SelectedPoolPricePublicationError(f"unsupported {label} fields: {sorted(unknown)}")


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SelectedPoolPricePublicationError(f"invalid {label}: {value}") from exc


def _symbol_list(source: Mapping[str, Any], key: str) -> list[str]:
    value = source.get(key)
    if not isinstance(value, list):
        raise SelectedPoolPricePublicationError(f"source {key} must be a list")
    normalized = [str(item).strip().upper() for item in value]
    if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
        raise SelectedPoolPricePublicationError(f"source {key} contains invalid symbols")
    return sorted(normalized)


def _project_provider_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    _assert_exact_keys(value, _PROVIDER_CONTRACT_KEYS, "provider contract")
    markets = value.get("markets")
    if not isinstance(markets, list) or not markets:
        raise SelectedPoolPricePublicationError("provider contract markets are invalid")
    projected = {key: copy.deepcopy(value[key]) for key in sorted(_SEMANTIC_PROVIDER_CONTRACT_KEYS)}
    projected["markets"] = sorted(str(item).strip().lower() for item in markets)
    if (
        not str(projected["name"]).strip()
        or not str(projected["source_family"]).strip()
        or projected["research_only"] is not True
    ):
        raise SelectedPoolPricePublicationError("provider contract boundary is invalid")
    return projected


def _project_terminal_lifecycle(value: Mapping[str, Any]) -> dict[str, Any]:
    _assert_exact_keys(value, _TERMINAL_LIFECYCLE_KEYS, "terminal lifecycle")
    references = value.get("public_references")
    if not isinstance(references, list):
        raise SelectedPoolPricePublicationError("terminal public references must be a list")
    normalized = [str(reference).strip() for reference in references]
    if any(not reference for reference in normalized) or len(normalized) != len(set(normalized)):
        raise SelectedPoolPricePublicationError("terminal public references are invalid")
    projected = copy.deepcopy(dict(value))
    projected["public_references"] = sorted(normalized)
    return projected


def _project_record(value: Mapping[str, Any]) -> dict[str, Any]:
    _assert_known_keys(value, _RECORD_KEYS, "provider record")
    symbol = str(value.get("symbol", "")).strip().upper()
    attempts = value.get("attempts")
    if (
        not symbol
        or not _is_sha256(value.get("output_sha256"))
        or not isinstance(value.get("rows"), int)
        or int(value["rows"]) <= 0
        or not isinstance(attempts, list)
        or any(not isinstance(attempt, Mapping) for attempt in attempts)
    ):
        raise SelectedPoolPricePublicationError("provider record identity is incomplete")
    for attempt in attempts:
        _assert_known_keys(attempt, _ATTEMPT_KEYS, "provider attempt")
        if attempt.get("ok") is not True and attempt.get("ok") is not False:
            raise SelectedPoolPricePublicationError("provider attempt outcome is invalid")
    projected = {
        key: copy.deepcopy(value[key])
        for key in sorted(_PUBLICATION_RECORD_FIELDS)
        if key in value
    }
    projected["symbol"] = symbol
    lifecycle = projected.get("terminal_lifecycle")
    if lifecycle is not None:
        if not isinstance(lifecycle, Mapping):
            raise SelectedPoolPricePublicationError("terminal lifecycle must be an object")
        projected["terminal_lifecycle"] = _project_terminal_lifecycle(lifecycle)
    return projected


def _validate_source_boundaries(source: Mapping[str, Any]) -> dict[str, list[str]]:
    lists = {key: _symbol_list(source, key) for key in _LIST_SOURCE_KEYS}
    stale = set(lists["stale_symbols"])
    terminal = set(lists["terminal_history_symbols"])
    lifecycle = set(lists["lifecycle_declared_terminal_symbols"])
    start = _date_value(source.get("start"), "source start")
    cutoff = _date_value(source.get("cutoff"), "source cutoff")
    listing_evidence = source.get("terminal_listing_evidence")
    if (
        source.get("schema_version") != SOURCE_SCHEMA
        or source.get("evidence_type") != SOURCE_EVIDENCE_TYPE
        or source.get("status") != "selected_pool_price_refresh_ready"
        or source.get("promotion_eligible") is not True
        or source.get("research_only") is not True
        or source.get("trade_ready") is not False
        or source.get("all_sources_ready") is not True
        or source.get("failure_count") != 0
        or lists["failed_symbols"]
        or lists["quarantined_symbols"]
        or lists["legacy_copied_symbols"]
        or lists["unresolved_stale_symbols"]
        or source.get("promotion_blocker") is not None
        or not isinstance(source.get("candidate_count"), int)
        or source["candidate_count"] != len(lists["candidate_symbols"])
        or str(source.get("market", "")).strip().lower() not in {"cn", "us"}
        or not str(source.get("pool_id", "")).strip()
        or start > cutoff
        or not isinstance(source.get("all_sources_current"), bool)
        or source.get("all_sources_current") is not (not stale)
        or not stale <= terminal <= lifecycle
        or not isinstance(listing_evidence, Mapping)
        or set(listing_evidence) != lifecycle
    ):
        raise SelectedPoolPricePublicationError("source manifest is not publication ready")
    for symbol, evidence in listing_evidence.items():
        if not isinstance(evidence, Mapping):
            raise SelectedPoolPricePublicationError(
                f"terminal listing evidence is invalid for {symbol}"
            )
        _assert_exact_keys(evidence, _TERMINAL_LISTING_KEYS, "terminal listing evidence")
        _date_value(evidence.get("terminal_date"), f"terminal date for {symbol}")
    return lists


def _fallback_authorization(
    record: Mapping[str, Any], provider_order: list[str]
) -> dict[str, Any]:
    symbol = str(record.get("symbol", "")).strip().upper()
    if record.get("action") != "fetched_full_refresh":
        raise SelectedPoolPricePublicationError(f"formal fallback {symbol} was not fully refreshed")
    try:
        yahoo_index = provider_order.index("yfinance")
    except ValueError as exc:
        raise SelectedPoolPricePublicationError("Yahoo fallback is not configured") from exc
    required = provider_order[:yahoo_index]
    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        raise SelectedPoolPricePublicationError("fallback attempts are invalid")
    for provider in required:
        matching = [
            attempt for attempt in attempts
            if isinstance(attempt, Mapping)
            and str(attempt.get("provider", "")).strip().lower() == provider
        ]
        if not matching or any(attempt.get("ok") is not False for attempt in matching):
            raise SelectedPoolPricePublicationError(
                f"formal fallback {symbol} lacks failed proof for {provider}"
            )
    if not any(
        isinstance(attempt, Mapping)
        and str(attempt.get("provider", "")).strip().lower() == "yfinance"
        and attempt.get("ok") is True
        for attempt in attempts
    ):
        raise SelectedPoolPricePublicationError(f"formal fallback {symbol} lacks Yahoo success proof")
    return {
        "failed_preferred_providers": sorted(required),
        "selected_provider": "yfinance",
        "symbol": symbol,
    }


def build_selected_pool_price_publication_manifest(source: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable, self-identifying provider publication evidence."""

    _assert_exact_keys(source, _SOURCE_KEYS, "source manifest")
    lists = _validate_source_boundaries(source)
    records = source.get("records")
    architecture = source.get("provider_architecture")
    selected = source.get("selected_providers")
    if (
        not _is_sha256(source.get("provider_identity_sha256"))
        or not isinstance(records, list)
        or not isinstance(architecture, Mapping)
        or not isinstance(selected, Mapping)
    ):
        raise SelectedPoolPricePublicationError("source provider identity is incomplete")
    _assert_exact_keys(architecture, _ARCHITECTURE_KEYS, "provider architecture")
    providers = architecture.get("providers")
    provider_order_raw = architecture.get("provider_order")
    if not isinstance(providers, Mapping) or not isinstance(provider_order_raw, list):
        raise SelectedPoolPricePublicationError("source provider architecture is invalid")
    provider_order = [str(item).strip().lower() for item in provider_order_raw]
    market = str(source["market"]).strip().lower()
    start = _date_value(source["start"], "source start")
    cutoff = _date_value(source["cutoff"], "source cutoff")

    raw_by_symbol = {
        str(record.get("symbol", "")).strip().upper(): record
        for record in records if isinstance(record, Mapping)
    }
    projected_records = [_project_record(record) for record in records if isinstance(record, Mapping)]
    projected_records.sort(key=lambda record: str(record["symbol"]))
    record_by_symbol = {str(record["symbol"]): record for record in projected_records}
    if len(raw_by_symbol) != len(records) or len(record_by_symbol) != len(records) or not records:
        raise SelectedPoolPricePublicationError("provider record symbols are invalid")

    expected_symbols = set(lists["candidate_symbols"])
    expected_symbols.update(lists["auxiliary_symbols"])
    expected_symbols.update(lists["comparison_reference_symbols"])
    benchmark = str(source.get("benchmark", "")).strip().upper()
    if benchmark:
        expected_symbols.add(benchmark)
    if set(record_by_symbol) != expected_symbols:
        raise SelectedPoolPricePublicationError("provider records do not match declared symbols")
    identity_contracts = source.get("identity_contracts")
    expected_identity_contracts = {
        symbol: contract
        for symbol in sorted(expected_symbols)
        if (
            contract := selected_pool_provider_identity_contract(market, symbol)
        ) is not None
    }
    if not isinstance(identity_contracts, Mapping) or dict(identity_contracts) != (
        expected_identity_contracts
    ):
        raise SelectedPoolPricePublicationError("provider identity contracts are inconsistent")
    for symbol, raw_record in raw_by_symbol.items():
        expected_contract = expected_identity_contracts.get(symbol)
        if raw_record.get("identity_contract") != expected_contract:
            raise SelectedPoolPricePublicationError(
                f"record identity contract is inconsistent for {symbol}"
            )

    normalized_selected = {
        str(symbol).strip().upper(): str(provider).strip().lower()
        for symbol, provider in selected.items()
    }
    provider_records = {
        symbol: str(record.get("provider", "")).strip().lower()
        for symbol, record in record_by_symbol.items()
        if str(record.get("provider", "")).strip()
    }
    if normalized_selected != provider_records:
        raise SelectedPoolPricePublicationError("selected provider mapping is inconsistent")

    terminal = set(lists["terminal_history_symbols"])
    for symbol, record in record_by_symbol.items():
        first_date = _date_value(record.get("first_date"), f"first date for {symbol}")
        last_date = _date_value(record.get("last_date"), f"last date for {symbol}")
        if first_date < start or first_date > last_date or last_date > cutoff:
            raise SelectedPoolPricePublicationError(
                f"provider record date boundary is invalid for {symbol}"
            )
        provider = provider_records.get(symbol)
        if provider:
            contract = providers.get(provider)
            if not isinstance(contract, Mapping) or raw_by_symbol[symbol].get("provider_contract") != contract:
                raise SelectedPoolPricePublicationError(
                    f"selected provider contract is inconsistent for {symbol}"
                )
            if not str(record.get("provider_symbol", "")).strip():
                raise SelectedPoolPricePublicationError(f"selected provider symbol is missing for {symbol}")
            try:
                validate_selected_pool_provider_identity(
                    market=market,
                    symbol=symbol,
                    provider_symbol=record.get("provider_symbol"),
                )
            except ValueError as exc:
                raise SelectedPoolPricePublicationError(str(exc)) from exc
            if last_date != cutoff:
                raise SelectedPoolPricePublicationError(
                    f"current provider record does not reach cutoff for {symbol}"
                )
            if market == "cn" and provider == "yfinance" and symbol not in set(
                lists["formal_auxiliary_fallback_symbols"]
            ):
                raise SelectedPoolPricePublicationError(
                    f"CN Yahoo provider is not an authorized formal auxiliary: {symbol}"
                )
        else:
            lifecycle = record.get("terminal_lifecycle")
            if symbol not in terminal or not isinstance(lifecycle, Mapping):
                raise SelectedPoolPricePublicationError(
                    f"provider-less record is not governed terminal history: {symbol}"
                )
            _assert_exact_keys(lifecycle, _TERMINAL_LIFECYCLE_KEYS, "terminal lifecycle")
            if (
                record.get("promotion_status") != "governed_terminal_history"
                or not _is_sha256(record.get("source_sha256"))
                or record.get("source_sha256") != lifecycle.get("governed_history_sha256")
                or record.get("source_path") != lifecycle.get("governed_history_path")
                or record.get("last_date") != lifecycle.get("terminal_date")
                or lifecycle.get("historical_rows_retained") is not True
                or lifecycle.get("active_universe_after_terminal_date_allowed") is not False
            ):
                raise SelectedPoolPricePublicationError(
                    f"terminal lifecycle contract is inconsistent for {symbol}"
                )

    selected_provider_contracts = {
        provider: _project_provider_contract(providers[provider])
        for provider in sorted(set(normalized_selected.values()))
        if isinstance(providers.get(provider), Mapping)
    }
    if set(selected_provider_contracts) != set(normalized_selected.values()):
        raise SelectedPoolPricePublicationError("selected provider contracts are incomplete")
    if any(
        str(contract.get("name", "")).strip().lower() != provider
        for provider, contract in selected_provider_contracts.items()
    ):
        raise SelectedPoolPricePublicationError("selected provider contract names are inconsistent")

    fallback_symbols = set(lists["formal_auxiliary_fallback_symbols"])
    if not fallback_symbols <= set(lists["auxiliary_symbols"]):
        raise SelectedPoolPricePublicationError("formal fallback must be an auxiliary")
    fallback_authorizations = []
    for symbol in sorted(fallback_symbols):
        if normalized_selected.get(symbol) != "yfinance":
            raise SelectedPoolPricePublicationError(f"formal fallback provider is invalid for {symbol}")
        fallback_authorizations.append(_fallback_authorization(raw_by_symbol[symbol], provider_order))

    projected = {
        key: copy.deepcopy(value)
        for key, value in source.items()
        if key not in _OPERATIONAL_SOURCE_KEYS | {"records", "provider_architecture"}
    }
    projected.update(lists)
    projected["selected_providers"] = dict(sorted(normalized_selected.items()))
    projected["source_schema_version"] = projected["schema_version"]
    projected["source_evidence_type"] = projected["evidence_type"]
    projected["schema_version"] = PUBLICATION_SCHEMA
    projected["evidence_type"] = PUBLICATION_EVIDENCE_TYPE
    projected["records"] = projected_records
    projected["provider_architecture"] = {
        "formal_auxiliary_fallback_authorizations": fallback_authorizations,
        "schema_version": str(architecture.get("schema_version", "")),
        "selected_provider_contracts": selected_provider_contracts,
        "selection_mode": str(architecture.get("selection_mode", "")),
    }
    projected["diagnostics_policy"] = copy.deepcopy(_DIAGNOSTICS_POLICY)
    _validate_publication_shape(projected | {"publication_identity_sha256": "0" * 64})
    _validate_publication_invariants(projected)
    projected["publication_identity_sha256"] = _sha256(_canonical_json(projected))
    return projected


def _validate_publication_shape(value: Mapping[str, Any]) -> None:
    _assert_exact_keys(value, _PUBLICATION_KEYS, "publication manifest")
    if (
        value.get("source_schema_version") != SOURCE_SCHEMA
        or value.get("source_evidence_type") != SOURCE_EVIDENCE_TYPE
        or value.get("diagnostics_policy") != _DIAGNOSTICS_POLICY
        or not _is_sha256(value.get("provider_identity_sha256"))
    ):
        raise SelectedPoolPricePublicationError("publication manifest identity is invalid")
    architecture = value.get("provider_architecture")
    records = value.get("records")
    if not isinstance(architecture, Mapping) or not isinstance(records, list):
        raise SelectedPoolPricePublicationError("publication manifest content is invalid")
    _assert_exact_keys(architecture, _PUBLICATION_ARCHITECTURE_KEYS, "publication architecture")
    contracts = architecture.get("selected_provider_contracts")
    authorizations = architecture.get("formal_auxiliary_fallback_authorizations")
    if not isinstance(contracts, Mapping) or not isinstance(authorizations, list):
        raise SelectedPoolPricePublicationError("publication provider contracts are invalid")
    for contract in contracts.values():
        if not isinstance(contract, Mapping):
            raise SelectedPoolPricePublicationError("publication provider contract is invalid")
        _assert_exact_keys(contract, _SEMANTIC_PROVIDER_CONTRACT_KEYS, "publication contract")
    for authorization in authorizations:
        if not isinstance(authorization, Mapping):
            raise SelectedPoolPricePublicationError("fallback authorization is invalid")
        _assert_exact_keys(authorization, _FALLBACK_AUTHORIZATION_KEYS, "fallback authorization")
    symbols = []
    for record in records:
        if not isinstance(record, Mapping):
            raise SelectedPoolPricePublicationError("publication records must be objects")
        _assert_known_keys(record, _PUBLICATION_RECORD_FIELDS, "publication record")
        symbol = str(record.get("symbol", "")).strip().upper()
        if (
            not symbol or not _is_sha256(record.get("output_sha256"))
            or not isinstance(record.get("rows"), int) or int(record["rows"]) <= 0
        ):
            raise SelectedPoolPricePublicationError("publication record identity is invalid")
        symbols.append(symbol)
    if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
        raise SelectedPoolPricePublicationError("publication symbols are invalid")


def _validate_publication_invariants(value: Mapping[str, Any]) -> None:
    lists = {key: _symbol_list(value, key) for key in _LIST_SOURCE_KEYS}
    if any(value.get(key) != normalized for key, normalized in lists.items()):
        raise SelectedPoolPricePublicationError("publication symbol lists are not canonical")
    stale = set(lists["stale_symbols"])
    terminal = set(lists["terminal_history_symbols"])
    lifecycle_symbols = set(lists["lifecycle_declared_terminal_symbols"])
    start = _date_value(value.get("start"), "publication start")
    cutoff = _date_value(value.get("cutoff"), "publication cutoff")
    market = str(value.get("market", "")).strip().lower()
    listing_evidence = value.get("terminal_listing_evidence")
    if (
        value.get("schema_version") != PUBLICATION_SCHEMA
        or value.get("evidence_type") != PUBLICATION_EVIDENCE_TYPE
        or value.get("status") != "selected_pool_price_refresh_ready"
        or value.get("promotion_eligible") is not True
        or value.get("research_only") is not True
        or value.get("trade_ready") is not False
        or value.get("all_sources_ready") is not True
        or value.get("failure_count") != 0
        or lists["failed_symbols"]
        or lists["quarantined_symbols"]
        or lists["legacy_copied_symbols"]
        or lists["unresolved_stale_symbols"]
        or value.get("promotion_blocker") is not None
        or not isinstance(value.get("candidate_count"), int)
        or value.get("candidate_count") != len(lists["candidate_symbols"])
        or market not in {"cn", "us"}
        or not str(value.get("pool_id", "")).strip()
        or start > cutoff
        or not isinstance(value.get("all_sources_current"), bool)
        or value.get("all_sources_current") is not (not stale)
        or not stale <= terminal <= lifecycle_symbols
        or not isinstance(listing_evidence, Mapping)
        or set(listing_evidence) != lifecycle_symbols
    ):
        raise SelectedPoolPricePublicationError("publication manifest boundary is invalid")
    for symbol, evidence in listing_evidence.items():
        if not isinstance(evidence, Mapping):
            raise SelectedPoolPricePublicationError(
                f"terminal listing evidence is invalid for {symbol}"
            )
        _assert_exact_keys(evidence, _TERMINAL_LISTING_KEYS, "terminal listing evidence")
        _date_value(evidence.get("terminal_date"), f"terminal date for {symbol}")

    records_raw = value.get("records")
    selected_raw = value.get("selected_providers")
    architecture = value.get("provider_architecture")
    if (
        not isinstance(records_raw, list)
        or not isinstance(selected_raw, Mapping)
        or not isinstance(architecture, Mapping)
    ):
        raise SelectedPoolPricePublicationError("publication content is incomplete")
    records = {
        str(record.get("symbol", "")).strip().upper(): record
        for record in records_raw
        if isinstance(record, Mapping)
    }
    expected_symbols = set(lists["candidate_symbols"])
    expected_symbols.update(lists["auxiliary_symbols"])
    expected_symbols.update(lists["comparison_reference_symbols"])
    benchmark = str(value.get("benchmark", "")).strip().upper()
    if benchmark:
        expected_symbols.add(benchmark)
    if len(records) != len(records_raw) or set(records) != expected_symbols:
        raise SelectedPoolPricePublicationError(
            "publication records do not match declared symbols"
        )
    selected = {
        str(symbol).strip().upper(): str(provider).strip().lower()
        for symbol, provider in selected_raw.items()
    }
    provider_records = {
        symbol: str(record.get("provider", "")).strip().lower()
        for symbol, record in records.items()
        if str(record.get("provider", "")).strip()
    }
    if selected != provider_records:
        raise SelectedPoolPricePublicationError("publication selected providers are inconsistent")

    contracts = architecture.get("selected_provider_contracts")
    if not isinstance(contracts, Mapping) or set(contracts) != set(selected.values()):
        raise SelectedPoolPricePublicationError("publication provider contracts are incomplete")
    for provider, contract in contracts.items():
        if (
            not isinstance(contract, Mapping)
            or str(contract.get("name", "")).strip().lower() != provider
            or market not in {
                str(item).strip().lower() for item in contract.get("markets", [])
            }
            or contract.get("research_only") is not True
        ):
            raise SelectedPoolPricePublicationError(
                f"publication provider contract is invalid for {provider}"
            )

    expected_identity_contracts = {
        symbol: contract
        for symbol in sorted(expected_symbols)
        if (
            contract := selected_pool_provider_identity_contract(market, symbol)
        ) is not None
    }
    identity_contracts = value.get("identity_contracts")
    if not isinstance(identity_contracts, Mapping) or dict(identity_contracts) != (
        expected_identity_contracts
    ):
        raise SelectedPoolPricePublicationError("publication identity contracts are inconsistent")

    fallback_symbols = set(lists["formal_auxiliary_fallback_symbols"])
    if not fallback_symbols <= set(lists["auxiliary_symbols"]):
        raise SelectedPoolPricePublicationError("publication fallback must be an auxiliary")
    authorizations_raw = architecture.get("formal_auxiliary_fallback_authorizations")
    if not isinstance(authorizations_raw, list):
        raise SelectedPoolPricePublicationError("publication fallback proof is missing")
    authorizations = {
        str(authorization.get("symbol", "")).strip().upper(): authorization
        for authorization in authorizations_raw
        if isinstance(authorization, Mapping)
    }
    if len(authorizations) != len(authorizations_raw) or set(authorizations) != fallback_symbols:
        raise SelectedPoolPricePublicationError("publication fallback proof is inconsistent")
    for symbol, authorization in authorizations.items():
        failed = authorization.get("failed_preferred_providers")
        if (
            authorization.get("selected_provider") != "yfinance"
            or selected.get(symbol) != "yfinance"
            or not isinstance(failed, list)
            or not failed
            or failed != sorted(set(str(provider).strip().lower() for provider in failed))
            or "yfinance" in failed
        ):
            raise SelectedPoolPricePublicationError(
                f"publication fallback proof is invalid for {symbol}"
            )

    for symbol, record in records.items():
        first_date = _date_value(record.get("first_date"), f"first date for {symbol}")
        last_date = _date_value(record.get("last_date"), f"last date for {symbol}")
        if first_date < start or first_date > last_date or last_date > cutoff:
            raise SelectedPoolPricePublicationError(
                f"publication record date boundary is invalid for {symbol}"
            )
        expected_identity = expected_identity_contracts.get(symbol)
        if record.get("identity_contract") != expected_identity:
            raise SelectedPoolPricePublicationError(
                f"publication record identity contract is invalid for {symbol}"
            )
        provider = provider_records.get(symbol)
        if provider:
            if (
                last_date != cutoff
                or not str(record.get("provider_symbol", "")).strip()
                or record.get("promotion_status")
                not in {
                    "source_semantics_recorded",
                    "formal_auxiliary_governed_yahoo_fallback",
                }
            ):
                raise SelectedPoolPricePublicationError(
                    f"publication provider record is invalid for {symbol}"
                )
            try:
                validate_selected_pool_provider_identity(
                    market=market,
                    symbol=symbol,
                    provider_symbol=record.get("provider_symbol"),
                )
            except ValueError as exc:
                raise SelectedPoolPricePublicationError(str(exc)) from exc
            if market == "cn" and provider == "yfinance" and symbol not in fallback_symbols:
                raise SelectedPoolPricePublicationError(
                    f"CN Yahoo provider is not an authorized formal auxiliary: {symbol}"
                )
        else:
            lifecycle = record.get("terminal_lifecycle")
            if symbol not in terminal or not isinstance(lifecycle, Mapping):
                raise SelectedPoolPricePublicationError(
                    f"publication terminal record is invalid for {symbol}"
                )
            _assert_exact_keys(lifecycle, _TERMINAL_LIFECYCLE_KEYS, "terminal lifecycle")
            references = lifecycle.get("public_references")
            if (
                record.get("promotion_status") != "governed_terminal_history"
                or not _is_sha256(record.get("source_sha256"))
                or record.get("source_sha256") != lifecycle.get("governed_history_sha256")
                or record.get("source_path") != lifecycle.get("governed_history_path")
                or record.get("last_date") != lifecycle.get("terminal_date")
                or lifecycle.get("historical_rows_retained") is not True
                or lifecycle.get("active_universe_after_terminal_date_allowed") is not False
                or not isinstance(references, list)
                or references != sorted(set(str(reference).strip() for reference in references))
            ):
                raise SelectedPoolPricePublicationError(
                    f"publication terminal lifecycle is invalid for {symbol}"
                )


def load_selected_pool_price_publication_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedPoolPricePublicationError(f"invalid publication manifest: {path}") from exc
    if not isinstance(value, dict):
        raise SelectedPoolPricePublicationError("publication manifest must be an object")
    _validate_publication_shape(value)
    declared = str(value.pop("publication_identity_sha256", ""))
    actual = _sha256(_canonical_json(value))
    value["publication_identity_sha256"] = declared
    if not _is_sha256(declared) or declared != actual:
        raise SelectedPoolPricePublicationError("publication manifest identity mismatch")
    _validate_publication_invariants(value)
    return value


def write_selected_pool_price_publication_manifest(path: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    projected = build_selected_pool_price_publication_manifest(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(projected))
    return projected


def verify_selected_pool_price_publication_manifest(
    path: Path, source: Mapping[str, Any]
) -> dict[str, Any]:
    observed = load_selected_pool_price_publication_manifest(path)
    expected = build_selected_pool_price_publication_manifest(source)
    if observed != expected:
        raise SelectedPoolPricePublicationError("publication manifest projection mismatch")
    return observed
