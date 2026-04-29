import base64
import time
from pathlib import Path

from fastapi.testclient import TestClient

from api_server import app
from src.api import dependencies as deps


def _auth_headers() -> dict[str, str]:
    token = base64.b64encode(b"agent:alpha2026").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _reset_job_service(tmp_path: Path) -> None:
    deps._JOB_SERVICE = None
    db_path = tmp_path / "metadata.db"
    # Set env before creating the singleton to isolate tests from local metadata DB.
    import os

    os.environ["TRADING_ASSISTANT_METADATA_DB_PATH"] = str(db_path)


def test_jobs_detail_and_panic_endpoint(tmp_path: Path):
    _reset_job_service(tmp_path)
    headers = _auth_headers()

    with TestClient(app) as client:
        js = deps.get_job_service()
        job_id = "panic_job_for_test"
        js.create_job(
            {
                "id": job_id,
                "type": "unit_test",
                "status": "running",
                "created_at": time.time(),
                "commands": [],
            }
        )

        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["job"]["id"] == job_id
        assert resp.json()["job"]["status"] == "running"

        panic_resp = client.post("/api/system/panic", json={"reason": "unit-test"}, headers=headers)
        assert panic_resp.status_code == 200
        assert panic_resp.json()["ok"] is True
        assert panic_resp.json()["halted_jobs"] >= 1

        updated = js.get_job(job_id)
        assert updated is not None
        assert updated["status"] == "failed"
        assert "SYSTEM_PANIC" in str(updated.get("error") or "")


def test_jobs_stream_endpoint_emits_log_lines_and_done_event(tmp_path: Path):
    _reset_job_service(tmp_path)
    headers = _auth_headers()

    log_path = tmp_path / "job.log"
    log_path.write_text("line-one\nline-two\n", encoding="utf-8")

    with TestClient(app) as client:
        js = deps.get_job_service()
        job_id = "stream_job_for_test"
        js.create_job(
            {
                "id": job_id,
                "type": "unit_test",
                "status": "succeeded",
                "created_at": time.time(),
                "log_path": str(log_path),
                "commands": [],
            }
        )

        body = ""
        with client.stream("GET", f"/api/jobs/{job_id}/stream", headers=headers) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in str(resp.headers.get("content-type") or "")
            for chunk in resp.iter_text():
                if not chunk:
                    continue
                body += chunk
                if "event: done" in body:
                    break

        assert "line-one" in body
        assert "line-two" in body
        assert "event: done" in body
