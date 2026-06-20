from __future__ import annotations

import base64
import sys
from pathlib import Path

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
