"""Validate the live GitHub Pages release against governed artifact contracts."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    validate_catalog as validate_model_run_catalog,
    validate_manifest as validate_model_run_manifest,
)

from src.artifacts.strategy_operations import (
    StrategyOperationsError,
    validate_operations_payload,
)

SHELL_BOOTSTRAP_MARKERS = ('<div id="root"></div>', '<script type="module"')


class ReleaseVerificationError(RuntimeError):
    """Raised when the deployed release violates the publication contract."""


@dataclass(frozen=True)
class PublishedFormalRun:
    model_family_id: str
    model_version_id: str
    run_id: str
    bundle_id: str
    manifest_path: str
    manifest_sha256: str
    evidence_cutoff: str


@dataclass(frozen=True)
class PublishedSection:
    section_id: str
    path: str
    byte_size: int
    sha256: str


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReleaseVerificationError(f"{label} must be a JSON object")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReleaseVerificationError(f"{label} must be a list")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError(f"{label} must be a non-empty string")
    return value


def _safe_path(value: object, *, label: str) -> str:
    path = _string(value, label=label).replace("\\", "/")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ReleaseVerificationError(f"{label} is unsafe")
    return pure.as_posix()


def _digest(value: object, *, label: str) -> str:
    digest = _string(value, label=label)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ReleaseVerificationError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _json(payload: bytes, *, label: str) -> object:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"{label} is not valid JSON") from exc


def validate_deployment(payload: object, *, expected_commit: str) -> None:
    deployment = _mapping(payload, label="deployment")
    deployed_commit = _string(deployment.get("commit_sha"), label="deployment.commit_sha")
    if deployed_commit != expected_commit:
        raise ReleaseVerificationError(
            f"stale deployment: expected {expected_commit}, found {deployed_commit}"
        )


def validate_formal_catalog(payload: object) -> tuple[PublishedFormalRun, ...]:
    """Validate every accepted model published by the governed formal catalog.

    The formal catalog is the source of truth. Release verification must not
    maintain a second model allow-list that drifts whenever a baseline changes.
    """
    catalog = _mapping(payload, label="formal Bundle v2 catalog")
    try:
        validate_model_run_catalog(catalog)
    except ModelRunBundleV2Error as exc:
        raise ReleaseVerificationError(f"invalid formal Bundle v2 catalog: {exc}") from exc
    if catalog.get("channel") != "formal":
        raise ReleaseVerificationError("formal catalog channel must be formal")
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise ReleaseVerificationError("formal catalog research boundary is invalid")

    records: list[PublishedFormalRun] = []
    observed_versions: set[str] = set()
    for index, value in enumerate(
        _sequence(catalog.get("records"), label="formal catalog records")
    ):
        record = _mapping(value, label=f"formal catalog record {index}")
        version = _string(record.get("model_version_id"), label=f"record {index}.model_version_id")
        if version in observed_versions:
            raise ReleaseVerificationError(f"duplicate formal model version: {version}")
        observed_versions.add(version)
        if record.get("publication_status") != "accepted_formal_baseline":
            raise ReleaseVerificationError(f"{version} is not an accepted formal baseline")
        records.append(
            PublishedFormalRun(
                model_family_id=_string(
                    record.get("model_family_id"),
                    label=f"record {index}.model_family_id",
                ),
                model_version_id=version,
                run_id=_string(record.get("run_id"), label=f"record {index}.run_id"),
                bundle_id=_digest(record.get("bundle_id"), label=f"record {index}.bundle_id"),
                manifest_path=_safe_path(
                    record.get("manifest_path"),
                    label=f"record {index}.manifest_path",
                ),
                manifest_sha256=_digest(
                    record.get("manifest_sha256"),
                    label=f"record {index}.manifest_sha256",
                ),
                evidence_cutoff=_string(
                    record.get("evidence_cutoff"),
                    label=f"record {index}.evidence_cutoff",
                ),
            )
        )
    if not records:
        raise ReleaseVerificationError("formal catalog contains no accepted model runs")
    return tuple(records)


def validate_formal_manifest(
    record: PublishedFormalRun,
    payload: bytes,
) -> tuple[Mapping[str, object], tuple[PublishedSection, ...]]:
    digest = hashlib.sha256(payload).hexdigest()
    if digest != record.manifest_sha256:
        raise ReleaseVerificationError(
            f"manifest digest mismatch for {record.model_version_id}: "
            f"expected {record.manifest_sha256}, found {digest}"
        )
    manifest = _mapping(_json(payload, label=record.manifest_path), label=record.manifest_path)
    try:
        validate_model_run_manifest(manifest)
    except ModelRunBundleV2Error as exc:
        raise ReleaseVerificationError(
            f"invalid formal manifest for {record.model_version_id}: {exc}"
        ) from exc
    expected_identity = (
        record.model_family_id,
        record.model_version_id,
        record.run_id,
        record.bundle_id,
        record.evidence_cutoff,
    )
    actual_identity = (
        manifest.get("model_family_id"),
        manifest.get("model_version_id"),
        manifest.get("run_id"),
        manifest.get("bundle_id"),
        manifest.get("evidence_cutoff"),
    )
    if actual_identity != expected_identity:
        raise ReleaseVerificationError(
            f"catalog/manifest identity mismatch for {record.model_version_id}"
        )
    if (
        manifest.get("publication_channel") != "formal"
        or manifest.get("publication_status") != "accepted_formal_baseline"
    ):
        raise ReleaseVerificationError(
            f"formal channel/status mismatch for {record.model_version_id}"
        )
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise ReleaseVerificationError(f"research boundary mismatch for {record.model_version_id}")

    sections: list[PublishedSection] = []
    for index, value in enumerate(_sequence(manifest.get("sections"), label="manifest sections")):
        section = _mapping(value, label=f"manifest section {index}")
        if section.get("availability_status") != "available":
            continue
        byte_size = section.get("byte_size")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise ReleaseVerificationError(
                f"invalid section byte_size for {record.model_version_id}"
            )
        sections.append(
            PublishedSection(
                section_id=_string(
                    section.get("section_id"),
                    label=f"section {index}.section_id",
                ),
                path=_safe_path(section.get("path"), label=f"section {index}.path"),
                byte_size=byte_size,
                sha256=_digest(section.get("sha256"), label=f"section {index}.sha256"),
            )
        )
    if not any(section.section_id == "summary" for section in sections):
        raise ReleaseVerificationError(
            f"summary section is unavailable for {record.model_version_id}"
        )
    return manifest, tuple(sections)


def validate_formal_section(
    record: PublishedFormalRun,
    section: PublishedSection,
    payload: bytes,
) -> None:
    if len(payload) != section.byte_size:
        raise ReleaseVerificationError(
            f"section size mismatch for {record.model_version_id}/{section.section_id}: "
            f"expected {section.byte_size}, found {len(payload)}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if digest != section.sha256:
        raise ReleaseVerificationError(f"section digest mismatch for {record.model_version_id}/{section.section_id}: expected {section.sha256}, found {digest}")
    decoded = _json(payload, label=f"{record.model_version_id}/{section.path}")
    if section.section_id != "summary":
        return
    summary = _mapping(decoded, label=f"{record.model_version_id} summary")
    if (
        summary.get("model_version_id") != record.model_version_id
        or summary.get("run_id") != record.run_id
    ):
        raise ReleaseVerificationError(f"summary identity mismatch for {record.model_version_id}")
    _string(
        summary.get("display_name"),
        label=f"{record.model_version_id}.display_name",
    )
    if summary.get("research_only") is not True or summary.get("trade_ready") is not False:
        raise ReleaseVerificationError(
            f"summary research boundary mismatch for {record.model_version_id}"
        )


def validate_public_operations(
    payload: object, records: Sequence[PublishedFormalRun]
) -> None:
    """Enforce the public shell before upload and against the live release."""
    operations = _mapping(payload, label="strategy operations")
    if set(operations) != {
        "schema_version", "generated_at", "research_only", "trade_ready", "records"
    }:
        raise ReleaseVerificationError("public strategy operations have unexpected fields")
    try:
        validate_operations_payload(operations)
    except StrategyOperationsError as exc:
        raise ReleaseVerificationError(f"invalid public strategy operations: {exc}") from exc
    fixed_fields: dict[str, object] = {
        "status": "blocked",
        "read_state": "protected",
        "as_of": None,
        "latest_completed_session": None,
        "state_label": "Runtime current operations",
        "decision_reason": "Current holdings and signals are delivered from the runtime access plane.",
        "allocations": [],
        "turnover": None,
        "estimated_cost": None,
        "data_freshness": "unknown",
        "factor_freshness": "blocked",
        "delivery_status": "not available",
        "source_label": "Runtime current operations",
        "source_href": None,
        "note": "Current holdings, targets, drivers and decision-ledger provenance are never included in the public static bundle.",
        "factor_evidence": [],
    }
    allowed_fields = set(fixed_fields) | {
        "strategy_id", "model_version_id", "decision_cadence",
        "next_decision_policy", "source_identity",
    }
    by_version = {record.model_version_id: record for record in records}
    rows = [
        _mapping(row, label="strategy operation")
        for row in _sequence(operations.get("records"), label="strategy operations records")
    ]
    if len(rows) != len(by_version) or {
        row.get("model_version_id") for row in rows
    } != set(by_version):
        raise ReleaseVerificationError("strategy operations differ from the formal catalog")
    for row in rows:
        if set(row) != allowed_fields or any(
            row.get(key) != value for key, value in fixed_fields.items()
        ):
            raise ReleaseVerificationError("public strategy operations expose protected evidence")
        version = _string(row.get("model_version_id"), label="operations model version")
        record = by_version[version]
        expected_identity = {
            "formal_bundle_id": record.bundle_id,
            "formal_run_id": record.run_id,
            "formal_evidence_cutoff": record.evidence_cutoff,
            "ledger_fingerprint": None,
            "signal_sha256": None,
            "factor_catalog_implementation_hash": None,
            "workflow_run_id": None,
            "commit_sha": None,
            "github_issue_number": None,
        }
        if row.get("source_identity") != expected_identity:
            raise ReleaseVerificationError("public strategy operations source identity mismatch")


def validate_shell(payload: bytes) -> None:
    """Validate stable app bootstrap structure instead of product copy."""
    shell = payload.decode("utf-8", errors="replace")
    missing = [marker for marker in SHELL_BOOTSTRAP_MARKERS if marker not in shell]
    if missing:
        raise ReleaseVerificationError(
            f"deployed shell is missing bootstrap markers: {missing}"
        )


def _cache_busted_url(base_url: str, path: str) -> str:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}release_check={time.time_ns()}"


def fetch_bytes(base_url: str, path: str, *, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(
        _cache_busted_url(base_url, path),
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "alpha-engine-pages-release-verifier/2.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read()
    if not isinstance(payload, bytes):
        raise ReleaseVerificationError(f"{path} response body must be bytes")
    return payload


def verify_once(
    *,
    base_url: str,
    expected_commit: str,
    timeout_seconds: float,
) -> dict[str, object]:
    deployment_bytes = fetch_bytes(
        base_url,
        "deployment.json",
        timeout_seconds=timeout_seconds,
    )
    validate_deployment(
        _json(deployment_bytes, label="deployment.json"),
        expected_commit=expected_commit,
    )

    formal_root = "data/formal-model-runs"
    catalog_path = f"{formal_root}/catalog.json"
    catalog_bytes = fetch_bytes(base_url, catalog_path, timeout_seconds=timeout_seconds)
    records = validate_formal_catalog(_json(catalog_bytes, label=catalog_path))
    section_count = 0
    for record in records:
        manifest_path = f"{formal_root}/{record.manifest_path}"
        manifest_bytes = fetch_bytes(
            base_url,
            manifest_path,
            timeout_seconds=timeout_seconds,
        )
        _, sections = validate_formal_manifest(record, manifest_bytes)
        manifest_parent = PurePosixPath(record.manifest_path).parent
        for section in sections:
            relative_path = (manifest_parent / section.path).as_posix()
            payload = fetch_bytes(
                base_url,
                f"{formal_root}/{relative_path}",
                timeout_seconds=timeout_seconds,
            )
            validate_formal_section(record, section, payload)
            section_count += 1

    operations_bytes = fetch_bytes(
        base_url, "data/strategy-operations/snapshots.json", timeout_seconds=timeout_seconds
    )
    validate_public_operations(_json(operations_bytes, label="strategy operations"), records)

    shell_bytes = fetch_bytes(base_url, "index.html", timeout_seconds=timeout_seconds)
    validate_shell(shell_bytes)
    return {
        "status": "verified",
        "base_url": base_url,
        "commit_sha": expected_commit,
        "public_operations_verified": True,
        "formal_models": sorted(record.model_version_id for record in records),
        "formal_sections_verified": section_count,
        "research_only": True,
        "trade_ready": False,
    }


def verify_with_retries(
    *,
    base_url: str,
    expected_commit: str,
    attempts: int,
    delay_seconds: float,
    timeout_seconds: float,
) -> dict[str, object]:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return verify_once(
                base_url=base_url,
                expected_commit=expected_commit,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # bounded retry includes temporary network/CDN propagation failures
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise ReleaseVerificationError(
        f"release verification failed after {attempts} attempts: {last_error}"
    ) from last_error
