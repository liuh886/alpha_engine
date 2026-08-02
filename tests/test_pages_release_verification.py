from __future__ import annotations

import hashlib
import json

import pytest

from src.artifacts.pages_release_verification import (
    EXPECTED_EXCLUDED_CLASSES,
    PublishedRecord,
    ReleaseVerificationError,
    validate_catalog,
    validate_deployment,
    validate_record_bytes,
    validate_shell,
)


def _catalog() -> dict[str, object]:
    return {
        "publication_policy": "formal_named_baselines_only",
        "excluded_record_classes": sorted(EXPECTED_EXCLUDED_CLASSES),
        "research_only": True,
        "trade_ready": False,
        "records": [
            {
                "display_name": "QQQ Rotation v4.2",
                "display_order": 1,
                "model_id": "qqqi_qqq_tqqq_v4_2",
                "path": "qqqi_qqq_tqqq_v4_2.json",
                "publication_status": "accepted_formal_baseline",
                "sha256": "a" * 64,
            },
            {
                "display_name": "US x1.1",
                "display_order": 2,
                "model_id": "us_x1_1",
                "path": "us_x1_1.json",
                "publication_status": "accepted_formal_baseline",
                "sha256": "b" * 64,
            },
            {
                "display_name": "CN x1.0",
                "display_order": 3,
                "model_id": "cn_x1_0",
                "path": "cn_x1_0.json",
                "publication_status": "accepted_formal_baseline",
                "sha256": "c" * 64,
            },
        ],
    }


def test_accepts_expected_deployment_and_formal_catalog() -> None:
    validate_deployment({"commit_sha": "abc123"}, expected_commit="abc123")
    records = validate_catalog(_catalog())
    assert [record.model_id for record in records] == [
        "qqqi_qqq_tqqq_v4_2",
        "us_x1_1",
        "cn_x1_0",
    ]


def test_rejects_stale_deployment() -> None:
    with pytest.raises(ReleaseVerificationError, match="stale deployment"):
        validate_deployment({"commit_sha": "old"}, expected_commit="new")


def test_rejects_legacy_or_extra_formal_model() -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    records.append(
        {
            "display_name": "US x1.0",
            "display_order": 4,
            "model_id": "us_x1_0",
            "path": "us_x1_0.json",
            "publication_status": "accepted_formal_baseline",
            "sha256": "d" * 64,
        }
    )
    with pytest.raises(ReleaseVerificationError, match="unexpected formal model allow-list"):
        validate_catalog(catalog)


def test_rejects_boundary_regression() -> None:
    catalog = _catalog()
    catalog["trade_ready"] = True
    with pytest.raises(ReleaseVerificationError, match="trade_ready=false"):
        validate_catalog(catalog)


def test_verifies_record_hash_identity_and_boundary() -> None:
    payload = json.dumps(
        {"model_id": "us_x1_1", "research_only": True, "trade_ready": False},
        separators=(",", ":"),
    ).encode()
    record = PublishedRecord(
        model_id="us_x1_1",
        display_name="US x1.1",
        path="us_x1_1.json",
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    validate_record_bytes(record, payload)

    with pytest.raises(ReleaseVerificationError, match="digest mismatch"):
        validate_record_bytes(record, payload + b"\n")


def test_rejects_legacy_shell() -> None:
    validate_shell(b"<html>Complete backtest review</html>")
    with pytest.raises(ReleaseVerificationError, match="missing marker"):
        validate_shell(b"<html>Experiments</html>")
