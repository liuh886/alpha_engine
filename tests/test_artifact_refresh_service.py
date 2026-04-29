from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assistant.services.artifact_refresh_service import ArtifactRefreshService


def test_refresh_training_artifacts_runs_reporting_then_dashboard_build(monkeypatch):
    calls = []

    def fake_generate_report(market):
        calls.append(f"report_{market}")

    def fake_build_db():
        calls.append("build_db")

    # Mock the in-process calls
    import scripts.build_dashboard_db
    import src.reporting.generate

    monkeypatch.setattr(src.reporting.generate, "generate_report", fake_generate_report)
    monkeypatch.setattr(scripts.build_dashboard_db, "build_db", fake_build_db)

    svc = ArtifactRefreshService(project_root=ROOT, python_exe="python3")
    result = svc.refresh_training_artifacts(market="us")

    assert "report_us" in calls
    assert "build_db" in calls
    assert result["dashboard_db_refreshed"] is True


def test_refresh_backtest_artifacts_can_generate_latest_report(monkeypatch):
    calls = []

    def fake_build_db():
        calls.append("build_db")

    import scripts.build_dashboard_db

    monkeypatch.setattr(scripts.build_dashboard_db, "build_db", fake_build_db)

    svc = ArtifactRefreshService(
        project_root=ROOT,
        python_exe="python3",
        metadata_db_resolver=lambda _project_root: ROOT / "artifacts" / "metadata.db",
        latest_report_generator=lambda **_kwargs: {
            "report_rel_path": "reports/backtests/us/latest.html"
        },
    )

    result = svc.refresh_backtest_artifacts(market="us", refresh_dashboard_db=True)

    assert "build_db" in calls
    assert result["dashboard_db_refreshed"] is True
    assert result["report_rel_path"] == "reports/backtests/us/latest.html"
