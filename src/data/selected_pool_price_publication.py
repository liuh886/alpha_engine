"""Project selected-pool provider runs into stable publication evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SOURCE_SCHEMA = "1.2"
SOURCE_EVIDENCE_TYPE = "selected_pool_price_refresh_v1"
PUBLICATION_SCHEMA = "1.0.0"
PUBLICATION_EVIDENCE_TYPE = "selected_pool_price_publication_v1"
PUBLICATION_MANIFEST_NAME = "selected_pool_price_publication_manifest.json"

_SOURCE_KEYS = {
    "after",
    "all_sources_current",
    "all_sources_ready",
    "auxiliary_symbols",
    "before",
    "benchmark",
    "candidate_count",
    "candidate_symbols",
    "comparison_reference_symbols",
    "cutoff",
    "evidence_type",
    "failed_symbols",
    "failure_count",
    "formal_auxiliary_fallback_symbols",
    "identity_contracts",
    "legacy_copied_symbols",
    "lifecycle_declared_terminal_symbols",
    "market",
    "pool_id",
    "promotion_blocker",
    "promotion_eligible",
    "provider_architecture",
    "provider_identity_sha256",
    "quarantined_symbols",
    "records",
    "refresh_mode",
    "research_only",
    "schema_version",
    "selected_providers",
    "stale_symbols",
    "start",
    "status",
    "target_count",
    "targets",
    "terminal_history_symbols",
    "terminal_listing_evidence",
    "trade_ready",
    "unresolved_stale_symbols",
}
_OPERATIONAL_SOURCE_KEYS = {"after", "before", "refresh_mode", "target_count", "targets"}
_RECORD_KEYS = {
    "action",
    "attempts",
    "first_date",
    "identity_contract",
    "last_date",
    "output_sha256",
    "promotion_status",
    "provider",
    "provider_contract",
    "provider_symbol",
    "rows",
    "source_path",
    "source_sha256",
    "stale_reason",
    "symbol",
    "terminal_lifecycle",
}
_ATTEMPT_KEYS = {
    "circuit_breaker_open",
    "cutoff_complete",
    "error",
    "first_date",
    "independent_group",
    "last_date",
    "observed_last_date",
    "ok",
    "provider",
    "provider_contract",
    "provider_symbol",
    "requested_cutoff",
    "round",
    "rows",
    "schema_errors",
    "source_family",
}
_ARCHITECTURE_KEYS = {
    "formal_auxiliary_boundary",
    "health",
    "independent_provider_order",
    "provider_order",
    "providers",
    "public_source_boundary",
    "same_source_warning",
    "schema_version",
    "selection_mode",
}
_ATTEMPT_OUTCOME_KEYS = tuple(sorted(_ATTEMPT_KEYS - {"error", "provider_contract"}))
_DIAGNOSTICS_POLICY = {
    "excluded_record_fields": ["attempts[].error", "attempts[].provider_contract"],
    "excluded_top_level_fields": sorted(_OPERATIONAL_SOURCE_KEYS),
    "excluded_provider_architecture_fields": ["health"],
    "full_diagnostics_retained_in_run_artifact": True,
}
_PUBLICATION_KEYS = (
    _SOURCE_KEYS - _OPERATIONAL_SOURCE_KEYS
) | {
    "diagnostics_policy",
    "publication_identity_sha256",
    "source_evidence_type",
    "source_schema_version",
}
_PUBLICATION_RECORD_KEYS = (_RECORD_KEYS - {"attempts", "provider_contract"}) | {
    "attempt_outcomes"
}


class SelectedPoolPricePublicationError(ValueError):
    """Raised when provider evidence cannot be safely projected."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SelectedPoolPricePublicationError(
            f"unsupported {label} fields: "
            f"missing={sorted(expected - set(value))} unknown={sorted(set(value) - expected)}"
        )


def _assert_known_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    if unknown:
        raise SelectedPoolPricePublicationError(
            f"unsupported {label} fields: {sorted(unknown)}"
        )


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _project_attempt(value: Mapping[str, Any]) -> dict[str, Any]:
    _assert_known_keys(value, _ATTEMPT_KEYS, "provider attempt")
    if value.get("ok") is not True and value.get("ok") is not False:
        raise SelectedPoolPricePublicationError("provider attempt outcome is invalid")
    return {key: copy.deepcopy(value.get(key)) for key in _ATTEMPT_OUTCOME_KEYS}


def _project_record(value: Mapping[str, Any]) -> dict[str, Any]:
    _assert_known_keys(value, _RECORD_KEYS, "provider record")
    symbol = str(value.get("symbol", "")).strip().upper()
    output_sha = str(value.get("output_sha256", ""))
    attempts = value.get("attempts")
    if not symbol or not _is_sha256(output_sha) or not isinstance(attempts, list):
        raise SelectedPoolPricePublicationError("provider record identity is incomplete")
    projected = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key not in {"attempts", "provider_contract"}
    }
    projected["symbol"] = symbol
    projected["attempt_outcomes"] = [
        _project_attempt(attempt)
        for attempt in attempts
        if isinstance(attempt, Mapping)
    ]
    if len(projected["attempt_outcomes"]) != len(attempts):
        raise SelectedPoolPricePublicationError("provider attempts must be objects")
    return projected


def build_selected_pool_price_publication_manifest(
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Return stable, self-identifying provider publication evidence."""

    _assert_exact_keys(source, _SOURCE_KEYS, "source manifest")
    if (
        source.get("schema_version") != SOURCE_SCHEMA
        or source.get("evidence_type") != SOURCE_EVIDENCE_TYPE
        or source.get("status") != "selected_pool_price_refresh_ready"
        or source.get("promotion_eligible") is not True
        or source.get("research_only") is not True
        or source.get("trade_ready") is not False
        or source.get("failure_count") != 0
        or source.get("failed_symbols") != []
    ):
        raise SelectedPoolPricePublicationError("source manifest is not publication ready")
    provider_identity = str(source.get("provider_identity_sha256", ""))
    records = source.get("records")
    architecture = source.get("provider_architecture")
    if (
        not _is_sha256(provider_identity)
        or not isinstance(records, list)
        or not isinstance(architecture, Mapping)
    ):
        raise SelectedPoolPricePublicationError("source provider identity is incomplete")
    _assert_exact_keys(architecture, _ARCHITECTURE_KEYS, "provider architecture")

    projected = {
        key: copy.deepcopy(value)
        for key, value in source.items()
        if key not in _OPERATIONAL_SOURCE_KEYS | {"records", "provider_architecture"}
    }
    projected["source_schema_version"] = projected["schema_version"]
    projected["source_evidence_type"] = projected["evidence_type"]
    projected["schema_version"] = PUBLICATION_SCHEMA
    projected["evidence_type"] = PUBLICATION_EVIDENCE_TYPE
    projected["records"] = [
        _project_record(record) for record in records if isinstance(record, Mapping)
    ]
    if len(projected["records"]) != len(records):
        raise SelectedPoolPricePublicationError("provider records must be objects")
    symbols = [str(record["symbol"]) for record in projected["records"]]
    if not symbols or len(symbols) != len(set(symbols)):
        raise SelectedPoolPricePublicationError("provider record symbols are invalid")
    projected_architecture = copy.deepcopy(dict(architecture))
    projected_architecture.pop("health")
    projected["provider_architecture"] = projected_architecture
    projected["diagnostics_policy"] = copy.deepcopy(_DIAGNOSTICS_POLICY)
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
    _assert_exact_keys(
        architecture,
        _ARCHITECTURE_KEYS - {"health"},
        "publication provider architecture",
    )
    symbols: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise SelectedPoolPricePublicationError("publication records must be objects")
        _assert_known_keys(record, _PUBLICATION_RECORD_KEYS, "publication record")
        symbol = str(record.get("symbol", "")).strip().upper()
        if not symbol or not _is_sha256(record.get("output_sha256")):
            raise SelectedPoolPricePublicationError("publication record identity is invalid")
        outcomes = record.get("attempt_outcomes")
        if not isinstance(outcomes, list):
            raise SelectedPoolPricePublicationError("publication attempt outcomes are invalid")
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                raise SelectedPoolPricePublicationError(
                    "publication attempt outcomes must be objects"
                )
            _assert_exact_keys(
                outcome, set(_ATTEMPT_OUTCOME_KEYS), "publication attempt outcome"
            )
            if outcome.get("ok") is not True and outcome.get("ok") is not False:
                raise SelectedPoolPricePublicationError(
                    "publication attempt outcome is invalid"
                )
        symbols.append(symbol)
    if not symbols or len(symbols) != len(set(symbols)):
        raise SelectedPoolPricePublicationError("publication symbols are invalid")


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
    if (
        value.get("schema_version") != PUBLICATION_SCHEMA
        or value.get("evidence_type") != PUBLICATION_EVIDENCE_TYPE
        or value.get("research_only") is not True
        or value.get("trade_ready") is not False
        or value.get("status") != "selected_pool_price_refresh_ready"
        or value.get("promotion_eligible") is not True
    ):
        raise SelectedPoolPricePublicationError("publication manifest boundary is invalid")
    return value


def write_selected_pool_price_publication_manifest(
    path: Path,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    projected = build_selected_pool_price_publication_manifest(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(projected))
    return projected


def verify_selected_pool_price_publication_manifest(
    path: Path,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    observed = load_selected_pool_price_publication_manifest(path)
    expected = build_selected_pool_price_publication_manifest(source)
    if observed != expected:
        raise SelectedPoolPricePublicationError("publication manifest projection mismatch")
    return observed
