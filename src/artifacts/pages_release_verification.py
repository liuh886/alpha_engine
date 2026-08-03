"""Validate the live GitHub Pages release against the governed frontend contracts."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

EXPECTED_FORMAL_MODELS: tuple[tuple[str, str], ...] = (
    ("qqqi_qqq_tqqq_v4_2", "QQQ Rotation v4.2"),
    ("us_x1_1", "US x1.1"),
    ("cn_x1_0", "CN x1.0"),
)
EXPECTED_BUNDLE_MODEL_IDS = {"us_x1_1", "cn_x1_0"}
EXPECTED_EXCLUDED_CLASSES = {
    "exploratory_experiment",
    "candidate_grid",
    "rejected_candidate",
    "shadow_strategy",
}
EXPECTED_REQUIRED_BUNDLE_KINDS = {"model_index", "static_export_manifest"}
SHELL_MARKER = "Complete backtest review"


class ReleaseVerificationError(RuntimeError):
    """Raised when the deployed release violates the publication contract."""


@dataclass(frozen=True)
class PublishedRecord:
    model_id: str
    display_name: str
    path: str
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


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError(f"{label} must be a non-empty string")
    return value


def _safe_path(value: object, *, label: str) -> str:
    path = _string(value, label=label).replace("\\", "/")
    if path.startswith("/") or ".." in path.split("/"):
        raise ReleaseVerificationError(f"{label} is unsafe")
    return path


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


def validate_catalog(payload: object) -> tuple[PublishedRecord, ...]:
    catalog = _mapping(payload, label="formal catalog")
    if catalog.get("research_only") is not True:
        raise ReleaseVerificationError("formal catalog must retain research_only=true")
    if catalog.get("trade_ready") is not False:
        raise ReleaseVerificationError("formal catalog must retain trade_ready=false")
    if catalog.get("publication_policy") != "formal_named_baselines_only":
        raise ReleaseVerificationError("unexpected formal catalog publication policy")

    excluded = catalog.get("excluded_record_classes")
    if not isinstance(excluded, Sequence) or isinstance(excluded, (str, bytes)):
        raise ReleaseVerificationError("excluded_record_classes must be a list")
    if set(excluded) != EXPECTED_EXCLUDED_CLASSES:
        raise ReleaseVerificationError("formal catalog exclusion classes changed")

    records_value = catalog.get("records")
    if not isinstance(records_value, Sequence) or isinstance(records_value, (str, bytes)):
        raise ReleaseVerificationError("formal catalog records must be a list")

    records: list[PublishedRecord] = []
    observed_models: list[tuple[str, str]] = []
    for index, value in enumerate(records_value):
        record = _mapping(value, label=f"formal catalog record {index}")
        model_id = _string(record.get("model_id"), label=f"record {index}.model_id")
        display_name = _string(
            record.get("display_name"), label=f"record {index}.display_name"
        )
        path = _safe_path(record.get("path"), label=f"record {index}.path")
        digest = _digest(record.get("sha256"), label=f"record {index}.sha256")
        if record.get("publication_status") != "accepted_formal_baseline":
            raise ReleaseVerificationError(f"{model_id} is not an accepted formal baseline")
        if record.get("display_order") != index + 1:
            raise ReleaseVerificationError(f"{model_id} has an unexpected display order")
        observed_models.append((model_id, display_name))
        records.append(PublishedRecord(model_id, display_name, path, digest))

    if tuple(observed_models) != EXPECTED_FORMAL_MODELS:
        raise ReleaseVerificationError(
            f"unexpected formal model allow-list: {observed_models!r}"
        )
    if any(record.model_id == "us_x1_0" for record in records):
        raise ReleaseVerificationError("US x1.0 must not re-enter the formal catalog")
    return tuple(records)


def validate_record_bytes(record: PublishedRecord, payload: bytes) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    if digest != record.sha256:
        raise ReleaseVerificationError(
            f"digest mismatch for {record.model_id}: expected {record.sha256}, found {digest}"
        )
    package = _mapping(_json(payload, label=record.path), label=record.path)
    if package.get("model_id") != record.model_id:
        raise ReleaseVerificationError(f"model identity mismatch in {record.path}")
    if package.get("research_only") is not True or package.get("trade_ready") is not False:
        raise ReleaseVerificationError(f"research boundary mismatch in {record.path}")


def validate_bundle_manifest(
    payload: object,
) -> tuple[str, tuple[PublishedBundleArtifact, ...]]:
    bundle = _mapping(payload, label="research bundle manifest")
    schema_version = _string(bundle.get("schema_version"), label="bundle.schema_version")
    if schema_version.split(".", 1)[0] != "1":
        raise ReleaseVerificationError(f"unsupported research bundle schema: {schema_version}")
    if bundle.get("research_only") is not True or bundle.get("trade_ready") is not False:
        raise ReleaseVerificationError("research bundle boundary is invalid")
    bundle_id = _digest(bundle.get("bundle_id"), label="bundle.bundle_id")

    artifacts_value = bundle.get("artifacts")
    if not isinstance(artifacts_value, Sequence) or isinstance(
        artifacts_value, (str, bytes)
    ):
        raise ReleaseVerificationError("research bundle artifacts must be a list")

    required: list[PublishedBundleArtifact] = []
    for index, value in enumerate(artifacts_value):
        artifact = _mapping(value, label=f"bundle artifact {index}")
        if artifact.get("required") is not True:
            continue
        kind = _string(artifact.get("kind"), label=f"bundle artifact {index}.kind")
        path = _safe_path(artifact.get("path"), label=f"bundle artifact {index}.path")
        byte_size = artifact.get("byte_size")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise ReleaseVerificationError(
                f"bundle artifact {index}.byte_size must be a non-negative integer"
            )
        digest = _digest(
            artifact.get("sha256"), label=f"bundle artifact {index}.sha256"
        )
        required.append(PublishedBundleArtifact(kind, path, byte_size, digest))

    observed_kinds = {artifact.kind for artifact in required}
    if not EXPECTED_REQUIRED_BUNDLE_KINDS.issubset(observed_kinds):
        missing = sorted(EXPECTED_REQUIRED_BUNDLE_KINDS - observed_kinds)
        raise ReleaseVerificationError(
            f"research bundle is missing required artifact kinds: {missing}"
        )
    return bundle_id, tuple(required)


def validate_bundle_artifact_bytes(
    artifact: PublishedBundleArtifact, payload: bytes
) -> None:
    if len(payload) != artifact.byte_size:
        raise ReleaseVerificationError(
            f"bundle artifact size mismatch for {artifact.path}: "
            f"expected {artifact.byte_size}, found {len(payload)}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if digest != artifact.sha256:
        raise ReleaseVerificationError(
            f"bundle artifact digest mismatch for {artifact.path}: "
            f"expected {artifact.sha256}, found {digest}"
        )

    decoded = _json(payload, label=artifact.path)
    if artifact.kind == "model_index":
        if not isinstance(decoded, Sequence) or isinstance(decoded, (str, bytes)):
            raise ReleaseVerificationError("bundle model index must be a list")
        model_ids: list[str] = []
        for index, value in enumerate(decoded):
            model = _mapping(value, label=f"bundle model {index}")
            model_ids.append(_string(model.get("id"), label=f"bundle model {index}.id"))
        if len(model_ids) != len(set(model_ids)):
            raise ReleaseVerificationError("bundle model index contains duplicate IDs")
        missing = EXPECTED_BUNDLE_MODEL_IDS - set(model_ids)
        if missing:
            raise ReleaseVerificationError(
                f"bundle model index is missing formal metadata sources: {sorted(missing)}"
            )
    elif artifact.kind == "static_export_manifest":
        manifest = _mapping(decoded, label="static export manifest")
        if manifest.get("source") != "repository_research_store":
            raise ReleaseVerificationError("static export must use repository_research_store")
        if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
            raise ReleaseVerificationError("static export research boundary is invalid")
        blocked = manifest.get("blocked_gates", [])
        if isinstance(blocked, Sequence) and not isinstance(blocked, (str, bytes)):
            if "metadata_db_missing" in blocked:
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
            "User-Agent": "alpha-engine-pages-release-verifier/1.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read()
    if not isinstance(payload, bytes):
        raise ReleaseVerificationError(f"{path} response body must be bytes")
    return payload


def verify_once(
    *, base_url: str, expected_commit: str, timeout_seconds: float
) -> dict[str, object]:
    deployment_bytes = fetch_bytes(base_url, "deployment.json", timeout_seconds=timeout_seconds)
    validate_deployment(_json(deployment_bytes, label="deployment.json"), expected_commit=expected_commit)

    bundle_bytes = fetch_bytes(
        base_url, "bundle/alpha-engine-bundle.json", timeout_seconds=timeout_seconds
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

    catalog_path = "data/formal-backtests/catalog.json"
    catalog_bytes = fetch_bytes(base_url, catalog_path, timeout_seconds=timeout_seconds)
    records = validate_catalog(_json(catalog_bytes, label=catalog_path))
    for record in records:
        payload = fetch_bytes(
            base_url,
            f"data/formal-backtests/{record.path}",
            timeout_seconds=timeout_seconds,
        )
        validate_record_bytes(record, payload)

    shell_bytes = fetch_bytes(base_url, "index.html", timeout_seconds=timeout_seconds)
    validate_shell(shell_bytes)
    return {
        "status": "verified",
        "base_url": base_url,
        "commit_sha": expected_commit,
        "bundle_id": bundle_id,
        "required_bundle_artifacts": [artifact.path for artifact in required_artifacts],
        "formal_models": [record.model_id for record in records],
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
        except Exception as exc:  # bounded retry must include temporary network failures
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise ReleaseVerificationError(
        f"release verification failed after {attempts} attempts: {last_error}"
    ) from last_error
