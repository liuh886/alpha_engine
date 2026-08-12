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

EXPECTED_REQUIRED_BUNDLE_KINDS = {"model_index", "static_export_manifest"}
SHELL_MARKER = "Governed Model Runs"


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


@dataclass(frozen=True)
class PublishedBundleArtifact:
    kind: str
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
    _digest(
        summary.get("source_package_sha256"),
        label=f"{record.model_version_id}.source_package_sha256",
    )


def validate_bundle_manifest(payload: object) -> tuple[str, tuple[PublishedBundleArtifact, ...]]:
    bundle = _mapping(payload, label="research bundle manifest")
    schema_version = _string(bundle.get("schema_version"), label="bundle.schema_version")
    if schema_version.split(".", 1)[0] != "1":
        raise ReleaseVerificationError(f"unsupported research bundle schema: {schema_version}")
    if bundle.get("research_only") is not True or bundle.get("trade_ready") is not False:
        raise ReleaseVerificationError("research bundle boundary is invalid")
    bundle_id = _digest(bundle.get("bundle_id"), label="bundle.bundle_id")
    required: list[PublishedBundleArtifact] = []
    for index, value in enumerate(
        _sequence(bundle.get("artifacts"), label="research bundle artifacts")
    ):
        artifact = _mapping(value, label=f"bundle artifact {index}")
        if artifact.get("required") is not True:
            continue
        byte_size = artifact.get("byte_size")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise ReleaseVerificationError(f"bundle artifact {index}.byte_size is invalid")
        required.append(
            PublishedBundleArtifact(
                kind=_string(artifact.get("kind"), label=f"bundle artifact {index}.kind"),
                path=_safe_path(artifact.get("path"), label=f"bundle artifact {index}.path"),
                byte_size=byte_size,
                sha256=_digest(artifact.get("sha256"), label=f"bundle artifact {index}.sha256"),
            )
        )
    observed_kinds = {artifact.kind for artifact in required}
    if not EXPECTED_REQUIRED_BUNDLE_KINDS.issubset(observed_kinds):
        missing = sorted(EXPECTED_REQUIRED_BUNDLE_KINDS - observed_kinds)
        raise ReleaseVerificationError(
            f"research bundle is missing required artifact kinds: {missing}"
        )
    return bundle_id, tuple(required)


def validate_bundle_artifact_bytes(
    artifact: PublishedBundleArtifact,
    payload: bytes,
) -> None:
    if len(payload) != artifact.byte_size:
        raise ReleaseVerificationError(f"bundle artifact size mismatch for {artifact.path}")
    if hashlib.sha256(payload).hexdigest() != artifact.sha256:
        raise ReleaseVerificationError(f"bundle artifact digest mismatch for {artifact.path}")
    decoded = _json(payload, label=artifact.path)
    if artifact.kind == "model_index":
        models = _sequence(decoded, label="bundle model index")
        model_ids = [
            _string(
                _mapping(value, label=f"bundle model {index}").get("id"),
                label=f"bundle model {index}.id",
            )
            for index, value in enumerate(models)
        ]
        if len(model_ids) != len(set(model_ids)):
            raise ReleaseVerificationError("bundle model index contains duplicate IDs")
    elif artifact.kind == "static_export_manifest":
        manifest = _mapping(decoded, label="static export manifest")
        if manifest.get("source") != "repository_research_store":
            raise ReleaseVerificationError("static export must use repository_research_store")
        if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
            raise ReleaseVerificationError("static export research boundary is invalid")
        blocked = manifest.get("blocked_gates", [])
        if (
            isinstance(blocked, Sequence)
            and not isinstance(blocked, (str, bytes))
            and "metadata_db_missing" in blocked
        ):
            raise ReleaseVerificationError("static export fell back to missing metadata DB")


def validate_shell(payload: bytes) -> None:
    shell = payload.decode("utf-8", errors="replace")
    if SHELL_MARKER not in shell:
        raise ReleaseVerificationError(f"deployed shell is missing marker {SHELL_MARKER!r}")


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

    bundle_bytes = fetch_bytes(
        base_url,
        "bundle/alpha-engine-bundle.json",
        timeout_seconds=timeout_seconds,
    )
    bundle_id, required_artifacts = validate_bundle_manifest(
        _json(bundle_bytes, label="bundle/alpha-engine-bundle.json")
    )
    for artifact in required_artifacts:
        payload = fetch_bytes(
            base_url,
            f"bundle/{artifact.path}",
            timeout_seconds=timeout_seconds,
        )
        validate_bundle_artifact_bytes(artifact, payload)

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

    shell_bytes = fetch_bytes(base_url, "index.html", timeout_seconds=timeout_seconds)
    validate_shell(shell_bytes)
    return {
        "status": "verified",
        "base_url": base_url,
        "commit_sha": expected_commit,
        "bundle_id": bundle_id,
        "required_bundle_artifacts": [artifact.path for artifact in required_artifacts],
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
