"""Validate the live GitHub Pages release against the governed formal catalog."""

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
EXPECTED_EXCLUDED_CLASSES = {
    "exploratory_experiment",
    "candidate_grid",
    "rejected_candidate",
    "shadow_strategy",
}
SHELL_MARKER = "Complete backtest review"


class ReleaseVerificationError(RuntimeError):
    """Raised when the deployed release violates the publication contract."""


@dataclass(frozen=True)
class PublishedRecord:
    model_id: str
    display_name: str
    path: str
    sha256: str


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReleaseVerificationError(f"{label} must be a JSON object")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError(f"{label} must be a non-empty string")
    return value


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
        path = _string(record.get("path"), label=f"record {index}.path")
        digest = _string(record.get("sha256"), label=f"record {index}.sha256")
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
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"{record.path} is not valid JSON") from exc
    package = _mapping(decoded, label=record.path)
    if package.get("model_id") != record.model_id:
        raise ReleaseVerificationError(f"model identity mismatch in {record.path}")
    if package.get("research_only") is not True or package.get("trade_ready") is not False:
        raise ReleaseVerificationError(f"research boundary mismatch in {record.path}")


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
            "User-Agent": "alpha-engine-pages-release-verifier/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


def verify_once(
    *, base_url: str, expected_commit: str, timeout_seconds: float
) -> dict[str, object]:
    deployment_bytes = fetch_bytes(base_url, "deployment.json", timeout_seconds=timeout_seconds)
    validate_deployment(json.loads(deployment_bytes), expected_commit=expected_commit)

    catalog_path = "data/formal-backtests/catalog.json"
    catalog_bytes = fetch_bytes(base_url, catalog_path, timeout_seconds=timeout_seconds)
    records = validate_catalog(json.loads(catalog_bytes))
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
