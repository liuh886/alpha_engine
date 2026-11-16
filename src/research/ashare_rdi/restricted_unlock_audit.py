"""Read-only PIT coverage audit for the ``restricted_unlock`` event family.

This module does not fetch a provider, build an event-density series, score,
forecast, register a strategy or write a database. It classifies an already
generated governed event archive against the fields required before E(t) can be
constructed. Missing evidence stays ``unknown``; it is never counted as zero.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from src.data.company_events.event_store import normalize_company_information_event
from src.research.market_session_clock import exchange_sessions

from .coverage import FamilyCoverage, audit_coverage

EVENT_FAMILY = "restricted_unlock"
DEFAULT_UNIVERSE = "configs/research_universes/cn_selected_equities_v3.yaml"
DEFAULT_CONTRACT = "configs/data_contracts/company_information_event_phase2_v1.yaml"
DEFAULT_SOURCES = "configs/research_experiments/ashare_rdi_phase2_sources.yaml"
DEFAULT_POOL_REGISTRY = "configs/pools/selected_pool_registry_v1.yaml"
ADAPTER_PATH = "src/data/company_events/ashare_primary_announcements.py"

RECORD_REQUIRED_FIELDS = (
    (
        "original_announcement_identity",
        "Original CNINFO document identity plus announcement id or primary link",
    ),
    (
        "first_public_availability",
        "Timezone-aware first public availability timestamp (not merely retrieval)",
    ),
    ("source_evidence_hash", "SHA-256 digest of the source evidence"),
    (
        "story_identity_and_dedup",
        "Distinct real-world story identity and unique canonical event identity",
    ),
    ("effective_unlock_session", "Effective unlock session parsed from the announcement"),
    (
        "amendment_chain",
        "Revision/amendment chain or an explicit audited absence declaration",
    ),
    (
        "as_of_known_future_schedule",
        "Unlock schedule known before the effective session, using verified availability",
    ),
)
ARCHIVE_REQUIRED_FIELDS = (
    (
        "declared_universe_era_pit_membership",
        "Declared universe/era hash with PIT membership evidence",
    ),
    (
        "per_session_completeness_or_absence",
        "Verified per-session completeness or explicit absence matrix",
    ),
)

ADAPTER_OBSERVATIONS = (
    (
        "effective_unlock_session_not_parsed",
        'Adapter emits "effective_date": "" so the effective unlock session is absent.',
        '"effective_date": "",',
    ),
    (
        "amendment_chain_not_represented",
        'Adapter emits "revision_sequence": 0 and "supersedes_event_id": "" for every record.',
        '"revision_sequence": 0,',
    ),
    (
        "first_public_availability_not_captured",
        "Adapter derives announced_at at date-only midnight CST and never emits available_at.",
        "def _timestamp(date_text: str) -> str:",
    ),
    (
        "story_identity_not_represented",
        "Adapter emits no real-world story_id, so revisions and syndicated stories cannot be grouped.",
        "story_id",
    ),
    (
        "announcement_body_not_parsed_for_schedule",
        "Adapter classifies titles only; it does not parse the unlock date or share quantity from the filing body.",
        "announcement_body",
    ),
    (
        "reconciliation_is_asserted_not_corroborated",
        'Adapter hardcodes "reconciliation_status": "reconciled", "availability_status": "usable" and confidence 1.0.',
        '"reconciliation_status": "reconciled",',
    ),
    (
        "provider_response_bytes_not_archived",
        "Adapter emits a row-level source_hash but no provider response bytes or response digest.",
        "provider_response",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_sha256(value: Any) -> bool:
    text = _text(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _iso_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _aware_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _payload(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("payload")
    if isinstance(value, dict):
        return value
    raw = record.get("payload_json")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _record_checks(
    record: Mapping[str, Any],
    *,
    event_ids: set[str],
    duplicate_event_ids: set[str],
) -> dict[str, bool]:
    payload = _payload(record)
    announced_at = _aware_timestamp(record.get("announced_at"))
    retrieved_at = _aware_timestamp(record.get("retrieved_at"))
    announced_date = (
        announced_at.date()
        if announced_at is not None
        else _iso_date(_text(record.get("announced_at"))[:10])
    )
    effective_date = _iso_date(record.get("effective_date"))
    available_at = _aware_timestamp(
        record.get("available_at") or payload.get("available_at")
    )
    story_id = _text(record.get("story_id") or payload.get("story_id"))
    event_id = _text(record.get("event_id"))
    revision_sequence = int(record.get("revision_sequence") or 0)
    supersedes = _text(record.get("supersedes_event_id"))
    amendment_absence_checked = payload.get("amendment_absence_checked") is True

    announcement_identity = bool(_text(record.get("source_document_id"))) and bool(
        _text(payload.get("announcement_id")) or _text(payload.get("primary_link"))
    )
    availability_evidenced = (
        available_at is not None
        and announced_at is not None
        and available_at >= announced_at
        and retrieved_at is not None
        and available_at <= retrieved_at
    )
    story_evidenced = (
        bool(story_id)
        and bool(event_id)
        and event_id in event_ids
        and event_id not in duplicate_event_ids
    )
    effective_evidenced = (
        effective_date is not None
        and announced_date is not None
        and effective_date >= announced_date
    )
    amendment_evidenced = (
        revision_sequence > 0 and _is_sha256(supersedes)
    ) or amendment_absence_checked
    schedule_evidenced = (
        effective_evidenced
        and available_at is not None
        and effective_date is not None
        and available_at.date() < effective_date
    )
    return {
        "original_announcement_identity": announcement_identity,
        "first_public_availability": availability_evidenced,
        "source_evidence_hash": _is_sha256(record.get("source_hash")),
        "story_identity_and_dedup": story_evidenced,
        "effective_unlock_session": effective_evidenced,
        "amendment_chain": amendment_evidenced,
        "as_of_known_future_schedule": schedule_evidenced,
    }


def _archive_universe_evidenced(
    manifest: Mapping[str, Any] | None,
    *,
    records: Sequence[Mapping[str, Any]],
    declared_universe: str,
    declared_pool_symbols: Sequence[str] | None,
    declared_pool_sha256: str,
    declared_start: str,
    declared_cutoff: str,
) -> tuple[bool, list[str]]:
    if not isinstance(manifest, Mapping) or not records:
        return False, ["archive_manifest_or_records_absent"]
    failures: list[str] = []
    if _text(manifest.get("pool_id")) != declared_universe:
        failures.append("manifest_pool_id_mismatch")
    if _text(manifest.get("pool_sha256")).lower() != declared_pool_sha256.lower():
        failures.append("manifest_pool_hash_mismatch")
    if _text(manifest.get("period_start")) != declared_start:
        failures.append("manifest_period_start_mismatch")
    if _text(manifest.get("cutoff")) != declared_cutoff:
        failures.append("manifest_cutoff_mismatch")
    if manifest.get("pit_membership_verified") is not True:
        failures.append("pit_membership_not_verified")
    if declared_pool_symbols is not None:
        allowed = {str(symbol).zfill(6) for symbol in declared_pool_symbols}
        outside = sorted({_text(record.get("symbol")).zfill(6) for record in records} - allowed)
        if outside:
            failures.append(f"records_outside_declared_universe:{','.join(outside)}")
    return not failures, failures


def _coverage_result(
    coverage_rows: Sequence[Mapping[str, Any]],
    sessions: Sequence[str],
) -> dict[str, Any]:
    if (
        not isinstance(coverage_rows, (list, tuple))
        or not coverage_rows
        or not sessions
    ):
        return {
            "status": "missing",
            "expected_cells": len(sessions),
            "usable_cells": 0,
            "unverified_cells": 0,
            "missing_cells": len(sessions),
            "invalid_rows": [],
        }
    parsed: list[FamilyCoverage] = []
    invalid: list[dict[str, str]] = []
    for index, row in enumerate(coverage_rows):
        try:
            parsed.append(
                FamilyCoverage(
                    session=date.fromisoformat(_text(row.get("session"))),
                    family=_text(row.get("family")),
                    state=_text(row.get("state")),
                    source_id=_text(row.get("source_id")),
                    source_sha256=_text(row.get("source_sha256")),
                    point_in_time_archive_verified=bool(
                        row.get("point_in_time_archive_verified")
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            invalid.append({"index": str(index), "error": str(exc)})
    parsed_sessions = [date.fromisoformat(value) for value in sessions]
    result = audit_coverage(parsed, parsed_sessions, [EVENT_FAMILY])
    result["invalid_rows"] = invalid
    return result


def audit_restricted_unlock_records(
    records: Sequence[Mapping[str, Any]],
    *,
    sessions: Sequence[str],
    coverage_rows: Sequence[Mapping[str, Any]] = (),
    archive_manifest: Mapping[str, Any] | None = None,
    declared_universe: str = "cn_selected_equities_v3",
    declared_pool_symbols: Sequence[str] | None = None,
    declared_pool_sha256: str = "",
    declared_start: str,
    declared_cutoff: str,
) -> dict[str, Any]:
    """Classify a generated archive; never interpolate or score event absence."""

    valid: list[dict[str, Any]] = []
    ignored: list[dict[str, str]] = []
    event_id_counts: dict[str, int] = {}
    for record in records:
        try:
            normalized = normalize_company_information_event(record).to_dict()
        except (KeyError, TypeError, ValueError) as exc:
            ignored.append(
                {
                    "symbol": _text(record.get("symbol")),
                    "reason": str(exc),
                }
            )
            continue
        if normalized["event_family"] != EVENT_FAMILY:
            ignored.append(
                {
                    "symbol": normalized["symbol"],
                    "reason": f"unsupported_family:{normalized['event_family']}",
                }
            )
            continue
        valid.append({**record, **normalized})
        event_id = normalized["event_id"]
        event_id_counts[event_id] = event_id_counts.get(event_id, 0) + 1

    event_ids = set(event_id_counts)
    duplicate_event_ids = {key for key, count in event_id_counts.items() if count > 1}
    checks = {
        name: 0
        for name, _ in RECORD_REQUIRED_FIELDS
    }
    for record in valid:
        result = _record_checks(
            record,
            event_ids=event_ids,
            duplicate_event_ids=duplicate_event_ids,
        )
        for name, evidenced in result.items():
            checks[name] += int(evidenced)

    total = len(valid)
    required_fields: dict[str, dict[str, Any]] = {}
    for name, requirement in RECORD_REQUIRED_FIELDS:
        evidenced = checks[name]
        if total == 0 or evidenced == 0:
            status = "missing"
        elif evidenced == total:
            status = "evidenced"
        else:
            status = "partial"
        required_fields[name] = {
            "status": status,
            "requirement": requirement,
            "evidenced_records": evidenced,
            "total_records": total,
        }

    universe_evidenced, universe_failures = _archive_universe_evidenced(
        archive_manifest,
        records=valid,
        declared_universe=declared_universe,
        declared_pool_symbols=declared_pool_symbols,
        declared_pool_sha256=declared_pool_sha256,
        declared_start=declared_start,
        declared_cutoff=declared_cutoff,
    )
    coverage = _coverage_result(coverage_rows, sessions)
    coverage_evidenced = coverage["status"] == "ready"
    required_fields["declared_universe_era_pit_membership"] = {
        "status": "evidenced" if universe_evidenced else "missing",
        "requirement": ARCHIVE_REQUIRED_FIELDS[0][1],
        "evidenced_records": 1 if universe_evidenced else 0,
        "total_records": 1,
        "failures": universe_failures,
    }
    required_fields["per_session_completeness_or_absence"] = {
        "status": "evidenced" if coverage_evidenced else "missing",
        "requirement": ARCHIVE_REQUIRED_FIELDS[1][1],
        "evidenced_records": 1 if coverage_evidenced else 0,
        "total_records": 1,
        "expected_cells": coverage.get("expected_cells", 0),
        "usable_cells": coverage.get("usable_cells", 0),
    }

    gaps: dict[str, dict[str, Any]] = {}
    era = f"{declared_start}..{declared_cutoff}"
    if total == 0:
        gaps["no_restricted_unlock_event_archive"] = {
            "field": "event_archive",
            "era": era,
            "detail": "No governed restricted_unlock event records are present in the audited repository revision.",
        }
    archive_field_names = {name for name, _ in ARCHIVE_REQUIRED_FIELDS}
    for name, field in required_fields.items():
        if field["status"] != "evidenced" and name not in archive_field_names:
            gaps[f"field_not_evidenced:{name}"] = {
                "field": name,
                "era": era,
                "detail": field["requirement"],
            }
    if not universe_evidenced:
        gaps["archive_universe_era_pit_membership_not_evidenced"] = {
            "field": "declared_universe_era_pit_membership",
            "era": era,
            "detail": ";".join(universe_failures) or "archive manifest absent",
        }
    if not coverage_evidenced:
        gaps["per_session_absence_matrix_not_evidenced"] = {
            "field": "per_session_completeness_or_absence",
            "era": era,
            "detail": (
                f"{coverage.get('usable_cells', 0)} of "
                f"{coverage.get('expected_cells', 0)} expected restricted_unlock "
                "session cells are verified PIT coverage."
            ),
        }

    ready = total > 0 and all(
        field["status"] == "evidenced" for field in required_fields.values()
    )
    return {
        "status": "READY" if ready else "BLOCKED",
        "record_inventory": {
            "archive_present": total > 0,
            "record_count": len(records),
            "valid_restricted_unlock_records": total,
            "ignored_records": ignored,
            "duplicate_event_ids": sorted(duplicate_event_ids),
        },
        "required_fields": required_fields,
        "per_session_coverage": coverage,
        "gaps": list(gaps.values()),
    }


def adapter_capability_audit(adapter_text: str) -> dict[str, Any]:
    """Report adapter limitations only when the claimed code token is present."""

    observations = []
    for observation_id, claim, token in ADAPTER_OBSERVATIONS:
        if observation_id in {
            "story_identity_not_represented",
            "announcement_body_not_parsed_for_schedule",
            "provider_response_bytes_not_archived",
        }:
            detected = token not in adapter_text
        else:
            detected = token in adapter_text
        observations.append(
            {
                "id": observation_id,
                "claim": claim,
                "evidence_token": token,
                "detected": detected,
                "detection_rule": "absent" if observation_id in {
                    "story_identity_not_represented",
                    "announcement_body_not_parsed_for_schedule",
                    "provider_response_bytes_not_archived",
                } else "present",
            }
        )
    return {
        "module": ADAPTER_PATH,
        "sha256": hashlib.sha256(adapter_text.encode("utf-8")).hexdigest(),
        "observations": observations,
    }


def load_declared_pool(path: Path) -> tuple[str, list[str], int]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"universe YAML must be a mapping: {path}")
    pool_id = _text(payload.get("pool_id"))
    symbols = [_text(value).zfill(6) for value in payload.get("symbols", [])]
    candidate_count = int(payload.get("candidate_count", 0))
    if not pool_id or not symbols or candidate_count != len(symbols):
        raise ValueError("declared universe identity is not exact")
    if len(set(symbols)) != len(symbols):
        raise ValueError("declared universe contains duplicate symbols")
    return pool_id, symbols, candidate_count


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"event record line {line_number} is not a mapping")
        records.append(parsed)
    return records


def _read_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_receipt(
    root: Path,
    *,
    records_path: Path | None,
    coverage_path: Path | None,
    archive_manifest_path: Path | None,
    period_start: str,
    cutoff: str,
    receipt_date: str,
    repository_commit: str,
) -> dict[str, Any]:
    """Build the deterministic, hash-bound coverage/feasibility receipt."""

    root = root.resolve()
    pool_path = root / DEFAULT_UNIVERSE
    declared_universe, pool_symbols, candidate_count = load_declared_pool(pool_path)
    sessions = exchange_sessions("cn", period_start, cutoff)
    records = _read_jsonl(records_path)
    coverage_rows = _read_json(coverage_path) or []
    archive_manifest = _read_json(archive_manifest_path)

    audit = audit_restricted_unlock_records(
        records,
        sessions=sessions,
        coverage_rows=coverage_rows,
        archive_manifest=archive_manifest,
        declared_universe=declared_universe,
        declared_pool_symbols=pool_symbols,
        declared_pool_sha256=sha256_file(pool_path),
        declared_start=period_start,
        declared_cutoff=cutoff,
    )
    adapter_text = (root / ADAPTER_PATH).read_text(encoding="utf-8")
    if not isinstance(coverage_rows, (list, tuple)):
        coverage_rows = []
    adapter_audit = adapter_capability_audit(adapter_text)
    era = f"{period_start}..{cutoff}"

    gaps = list(audit["gaps"])
    gap_ids = {gap["field"] for gap in gaps}
    for observation in adapter_audit["observations"]:
        if observation["detected"] and observation["id"] not in gap_ids:
            gaps.append(
                {
                    "field": observation["id"],
                    "era": era,
                    "detail": observation["claim"],
                }
            )
    if (
        audit["required_fields"]["declared_universe_era_pit_membership"]["status"]
        != "evidenced"
    ):
        gaps.append(
            {
                "field": "pit_membership_history_not_evidenced",
                "era": era,
                "detail": (
                    "The selected-pool registry is a static current contract, not a "
                    "point-in-time membership history. No historical membership evidence "
                    "is archived with the event record."
                ),
            }
        )

    source_files = (
        DEFAULT_UNIVERSE,
        DEFAULT_CONTRACT,
        DEFAULT_SOURCES,
        DEFAULT_POOL_REGISTRY,
        ADAPTER_PATH,
        "src/data/company_events/event_store.py",
        "src/research/ashare_rdi/coverage.py",
        "src/research/ashare_rdi/phase2_audit.py",
    )
    source_hashes = {
        path: sha256_file(root / path) for path in source_files if (root / path).exists()
    }
    if audit["per_session_coverage"].get("status") != "missing":
        source_hashes[coverage_path.relative_to(root).as_posix()] = sha256_file(coverage_path)
    if archive_manifest is not None:
        source_hashes[archive_manifest_path.relative_to(root).as_posix()] = sha256_file(
            archive_manifest_path
        )
    if records:
        source_hashes[records_path.relative_to(root).as_posix()] = sha256_file(records_path)

    return {
        "schema_version": "ashare_rdi_restricted_unlock_coverage_v1",
        "receipt_date": receipt_date,
        "issue": 1272,
        "work_package": "restricted_unlock_pit_coverage_feasibility",
        "event_family": EVENT_FAMILY,
        "status": audit["status"],
        "research_only": True,
        "trade_ready": False,
        "declared_scope": {
            "universe": {
                "pool_id": declared_universe,
                "candidate_count": candidate_count,
                "pool_spec": DEFAULT_UNIVERSE,
                "pool_sha256": sha256_file(pool_path),
            },
            "era": {
                "start": period_start,
                "cutoff": cutoff,
                "basis": "phase-2 CN130 primary event-family generation defaults",
            },
            "current_governed_price_cutoff": "2026-11-13",
        },
        "record_inventory": audit["record_inventory"],
        "required_fields": audit["required_fields"],
        "per_session_coverage": audit["per_session_coverage"],
        "adapter_capability_audit": adapter_audit,
        "source_hashes": dict(sorted(source_hashes.items())),
        "repository_commit": repository_commit,
        "gaps": gaps,
        "audit_commands": [
            "git rev-parse HEAD",
            "git ls-files | grep -Ei 'cninfo|events\\.jsonl|restricted.*unlock'",
            "git log --all --oneline -- scripts/data/build_cn130_pit_event_families_phase2.py",
            "gh api 'repos/liuh886/alpha_engine/branches?per_page=100' --jq '.[].name'",
            (
                "python -m src.research.ashare_rdi.phase2_audit "
                "--restricted-unlock-coverage "
                f"--period-start {period_start} --cutoff {cutoff} "
                f"--receipt-date {receipt_date} "
                "--output docs/evidence/ashare_rdi/"
                "restricted_unlock_coverage_2026-11-16.json"
            ),
            "pytest tests/test_ashare_rdi_restricted_unlock_audit.py -q",
            (
                "ruff check src/research/ashare_rdi/restricted_unlock_audit.py "
                "src/research/ashare_rdi/phase2_audit.py "
                "tests/test_ashare_rdi_restricted_unlock_audit.py"
            ),
        ],
        "does_not_claim": [
            "no E(t) event-density series",
            "no per-session event count, frequency or rate",
            "no calibrated score, probability, threshold or weight",
            "no forecast or predictive power",
            "no strategy registration or change to active strategies",
            "no prospective as-of clock",
            "no claim that a missing event is zero",
            "no claim that unlock potential equals executed selling",
            "no qualification of the other nine RDI event families",
        ],
    }
