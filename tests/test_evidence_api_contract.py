from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_evidence_endpoint_uses_ledger_bundle_shape():
    from fastapi.testclient import TestClient

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from api_server import app

    creds = base64.b64encode(b"admin:alpha2026").decode()
    client = TestClient(app)

    resp = client.get(
        "/api/evidence/research_run/missing_run",
        headers={"Authorization": f"Basic {creds}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["bundle"]["subject_type"] == "research_run"
    assert data["bundle"]["subject_id"] == "missing_run"
    assert data["bundle"]["decision"] == "missing_artifact"


def test_latest_signal_discovery_endpoint_returns_report(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from api_server import app
    from src.api.routers import evidence

    report_dir = tmp_path / "artifacts" / "evidence" / "10d_signal_discovery"
    report_dir.mkdir(parents=True)
    report = {
        "schema_version": "1.0",
        "market": "us",
        "candidates": [{"candidate_kind": "lgbm_regressor"}],
        "summary": {"best_candidate": {"candidate": "lgbm_regressor/original"}},
    }
    (report_dir / "us_signal_discovery_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    monkeypatch.setattr(evidence, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evidence, "SIGNAL_DISCOVERY_DIR", report_dir)

    creds = base64.b64encode(b"admin:alpha2026").decode()
    response = TestClient(app).get(
        "/api/evidence/signal-discovery/latest?market=us",
        headers={"Authorization": f"Basic {creds}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["summary"]["best_candidate"]["candidate"] == (
        "lgbm_regressor/original"
    )
    assert payload["artifact_path"].endswith("us_signal_discovery_report.json")


def test_latest_signal_discovery_endpoint_is_truthful_when_missing(monkeypatch, tmp_path):
    from fastapi import HTTPException

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.api.routers import evidence

    monkeypatch.setattr(evidence, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evidence, "SIGNAL_DISCOVERY_DIR", tmp_path / "missing")

    with pytest.raises(HTTPException) as exc_info:
        evidence.get_latest_signal_discovery("us")
    assert exc_info.value.status_code == 404
