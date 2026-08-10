"""Model Run Bundle v2 identities, validation and canonical hashing."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "2.0.0"
MODEL_KINDS = {
    "rules_based_allocation",
    "cross_sectional_ranker",
    "forecast_model",
}
PUBLICATION_CHANNELS = {"local", "preview", "formal"}
PUBLICATION_STATUSES = {
    "local_only",
    "ci_validated_preview",
    "accepted_formal_baseline",
    "rejected",
    "blocked",
}
AVAILABILITY_STATUSES = {
    "available",
    "not_applicable",
    "not_computed",
    "not_retained",
    "blocked_by_source",
}
SECTION_IDS = {
    "summary",
    "performance",
    "risk",
    "robustness",
    "portfolio",
    "trades",
    "attribution",
    "diagnostics",
    "lineage",
    "decision",
}
METRIC_UNITS = {
    "total_return": "ratio",
    "annualized_return": "ratio",
    "benchmark_return": "ratio",
    "excess_return": "ratio",
    "annualized_volatility": "ratio",
    "sharpe_ratio": "decimal",
    "information_ratio": "decimal",
    "max_drawdown": "ratio",
    "turnover": "ratio",
    "transaction_cost": "ratio",
    "ic": "decimal",
    "rank_ic": "decimal",
    "icir": "decimal",
}
DIRECTIONS = {"higher_is_better", "lower_is_better", "descriptive"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ModelRunBundleV2Error(ValueError):
    """Raised when a bundle violates the v2 research artifact contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON deterministically for identities and section hashes."""

    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compute_bundle_id(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("bundle_id", None)
    return sha256_bytes(canonical_json_bytes(payload))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelRunBundleV2Error(message)


def _require_slug(value: object, label: str) -> str:
    text = str(value or "")
    _require(bool(SLUG.fullmatch(text)), f"invalid {label}: {text!r}")
    return text


def _require_sha(value: object, label: str) -> str:
    text = str(value or "")
    _require(bool(SHA256.fullmatch(text)), f"invalid {label}")
    return text


def _require_date(value: object, label: str) -> str:
    text = str(value or "")
    _require(bool(DATE.fullmatch(text)), f"invalid {label}: {text!r}")
    return text


def validate_metric(metric: Mapping[str, Any]) -> None:
    metric_id = str(metric.get("metric_id") or "")
    _require(metric_id in METRIC_UNITS, f"unsupported metric_id: {metric_id}")
    _require(metric.get("unit") == METRIC_UNITS[metric_id], f"invalid unit for {metric_id}")
    _require(metric.get("direction") in DIRECTIONS, f"invalid direction for {metric_id}")
    availability = metric.get("availability_status")
    _require(availability in AVAILABILITY_STATUSES, f"invalid availability for {metric_id}")
    value = metric.get("value")
    reason = metric.get("unavailable_reason")
    if availability == "available":
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{metric_id} value missing",
        )
        _require(reason is None, f"{metric_id} available metric cannot have unavailable_reason")
    else:
        _require(value is None, f"{metric_id} unavailable metric must have null value")
        _require(
            isinstance(reason, str) and bool(reason.strip()),
            f"{metric_id} unavailable reason missing",
        )
    sample_count = metric.get("sample_count")
    _require(
        sample_count is None or (isinstance(sample_count, int) and sample_count >= 0),
        f"invalid sample_count for {metric_id}",
    )
    _require(
        isinstance(metric.get("scope"), str) and bool(metric["scope"].strip()),
        f"scope missing for {metric_id}",
    )


def validate_section(section: Mapping[str, Any]) -> None:
    section_id = str(section.get("section_id") or "")
    _require(section_id in SECTION_IDS, f"unsupported section_id: {section_id}")
    availability = section.get("availability_status")
    _require(availability in AVAILABILITY_STATUSES, f"invalid availability for {section_id}")
    _require(
        isinstance(section.get("required_for_model_kind"), bool),
        f"required flag missing for {section_id}",
    )
    if availability == "available":
        path = str(section.get("path") or "")
        _require(
            path.endswith(".json") and not path.startswith("/"), f"invalid path for {section_id}"
        )
        _require(".." not in Path(path).parts, f"unsafe path for {section_id}")
        _require_sha(section.get("sha256"), f"{section_id} sha256")
        _require(
            isinstance(section.get("byte_size"), int) and section["byte_size"] >= 0,
            f"invalid byte_size for {section_id}",
        )
        _require(
            section.get("media_type") == "application/json", f"invalid media_type for {section_id}"
        )
        _require(section.get("reason") is None, f"available {section_id} cannot have reason")
    else:
        _require(
            isinstance(section.get("reason"), str) and bool(section["reason"].strip()),
            f"reason missing for {section_id}",
        )
        for key in ("path", "sha256", "byte_size", "media_type"):
            _require(section.get(key) is None, f"unavailable {section_id} cannot declare {key}")


def validate_manifest(manifest: Mapping[str, Any], *, verify_bundle_id: bool = True) -> None:
    _require(
        manifest.get("schema_version") == SCHEMA_VERSION, "unsupported manifest schema_version"
    )
    for key in ("model_family_id", "model_version_id", "run_id"):
        _require_slug(manifest.get(key), key)
    _require(manifest.get("model_kind") in MODEL_KINDS, "invalid model_kind")
    channel = manifest.get("publication_channel")
    status = manifest.get("publication_status")
    _require(channel in PUBLICATION_CHANNELS, "invalid publication_channel")
    _require(status in PUBLICATION_STATUSES, "invalid publication_status")
    _require(manifest.get("research_only") is True, "research_only must be true")
    _require(manifest.get("trade_ready") is False, "trade_ready must be false")
    if channel == "formal" or status == "accepted_formal_baseline":
        _require(
            channel == "formal" and status == "accepted_formal_baseline",
            "formal channel/status mismatch",
        )
    else:
        _require(
            status != "accepted_formal_baseline", "non-formal bundle cannot be accepted formal"
        )
    _require_date(manifest.get("evidence_cutoff"), "evidence_cutoff")

    comparability = manifest.get("comparability_key")
    _require(isinstance(comparability, Mapping), "comparability_key missing")
    for key in ("market", "trace_frequency", "horizon"):
        _require(
            isinstance(comparability.get(key), str) and bool(str(comparability[key]).strip()),
            f"comparability {key} missing",
        )
    for key in ("universe_id", "benchmark_id", "rebalance_contract_id", "cost_contract_id"):
        _require_slug(comparability.get(key), f"comparability.{key}")
    _require_date(comparability.get("start"), "comparability.start")
    _require_date(comparability.get("end"), "comparability.end")
    _require(
        str(comparability["start"]) <= str(comparability["end"]),
        "comparability interval is reversed",
    )

    sections = manifest.get("sections")
    _require(isinstance(sections, list) and len(sections) >= 2, "sections are missing")
    seen: set[str] = set()
    for value in sections:
        _require(isinstance(value, Mapping), "invalid section declaration")
        validate_section(value)
        section_id = str(value["section_id"])
        _require(section_id not in seen, f"duplicate section: {section_id}")
        seen.add(section_id)
    _require("summary" in seen, "summary section is required")
    summary = next(value for value in sections if value["section_id"] == "summary")
    _require(summary["availability_status"] == "available", "summary must be available")

    if verify_bundle_id:
        supplied = _require_sha(manifest.get("bundle_id"), "bundle_id")
        _require(
            supplied == compute_bundle_id(manifest), "bundle_id does not match canonical manifest"
        )


def validate_catalog(catalog: Mapping[str, Any]) -> None:
    _require(catalog.get("schema_version") == SCHEMA_VERSION, "unsupported catalog schema_version")
    channel = catalog.get("channel")
    _require(channel in PUBLICATION_CHANNELS, "invalid catalog channel")
    _require(catalog.get("research_only") is True, "catalog research_only must be true")
    _require(catalog.get("trade_ready") is False, "catalog trade_ready must be false")
    records = catalog.get("records")
    _require(isinstance(records, list), "catalog records missing")
    identities: set[tuple[str, str, str]] = set()
    bundle_ids: set[str] = set()
    for record in records:
        _require(isinstance(record, Mapping), "invalid catalog record")
        identity = tuple(
            _require_slug(record.get(key), key)
            for key in ("model_family_id", "model_version_id", "run_id")
        )
        _require(identity not in identities, f"duplicate run identity: {identity}")
        identities.add(identity)
        bundle_id = _require_sha(record.get("bundle_id"), "catalog bundle_id")
        _require(bundle_id not in bundle_ids, f"duplicate bundle_id: {bundle_id}")
        bundle_ids.add(bundle_id)
        status = record.get("publication_status")
        _require(status in PUBLICATION_STATUSES, "invalid catalog publication_status")
        if channel == "formal":
            _require(
                status == "accepted_formal_baseline", "formal catalog contains non-formal record"
            )
        else:
            _require(
                status != "accepted_formal_baseline", "preview/local catalog contains formal record"
            )
        _require_sha(record.get("manifest_sha256"), "manifest_sha256")
        _require_date(record.get("evidence_cutoff"), "catalog evidence_cutoff")
    sorted_records = sorted(
        records, key=lambda row: (row["model_family_id"], row["model_version_id"], row["run_id"])
    )
    _require(records == sorted_records, "catalog records must be deterministically ordered")


def validate_decision(
    decision: Mapping[str, Any], *, manifest: Mapping[str, Any] | None = None
) -> None:
    _require(
        decision.get("schema_version") == SCHEMA_VERSION, "unsupported decision schema_version"
    )
    _require_slug(decision.get("run_id"), "decision run_id")
    _require_sha(decision.get("bundle_id"), "decision bundle_id")
    _require(
        decision.get("verdict") in {"supported", "not_supported", "blocked"}, "invalid verdict"
    )
    _require(decision.get("status") in {"pending_review", "completed"}, "invalid decision status")
    _require(decision.get("research_only") is True, "decision research_only must be true")
    _require(decision.get("trade_ready") is False, "decision trade_ready must be false")
    for group in ("gates", "supporting_evidence", "contradictory_evidence"):
        claims = decision.get(group)
        _require(isinstance(claims, list), f"decision {group} missing")
        for claim in claims:
            _require(isinstance(claim, Mapping), f"invalid decision claim in {group}")
            _require_slug(claim.get("claim_id"), "claim_id")
            _require(
                claim.get("outcome") in {"passed", "failed", "blocked", "informational"},
                "invalid claim outcome",
            )
            _require(
                isinstance(claim.get("statement"), str) and bool(claim["statement"].strip()),
                "claim statement missing",
            )
            path = str(claim.get("source_path") or "")
            _require(
                path.endswith(".json") and ".." not in Path(path).parts, "invalid claim source_path"
            )
            _require_sha(claim.get("source_sha256"), "claim source_sha256")
    _require(
        isinstance(decision.get("next_permitted_validation_step"), str)
        and bool(decision["next_permitted_validation_step"].strip()),
        "next permitted validation step missing",
    )
    if manifest is not None:
        _require(decision["run_id"] == manifest.get("run_id"), "decision run_id mismatch")
        _require(decision["bundle_id"] == manifest.get("bundle_id"), "decision bundle_id mismatch")


def comparability_identity(manifest: Mapping[str, Any]) -> str:
    validate_manifest(manifest)
    return sha256_bytes(canonical_json_bytes(manifest["comparability_key"]))
