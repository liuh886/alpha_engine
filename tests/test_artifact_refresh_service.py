from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assistant.services.artifact_refresh_service import ArtifactRefreshService


def test_refresh_training_artifacts_runs_reporting_then_dashboard_build():
    calls: list[list[str]] = []

    def fake_run(cmd, *, check):
        calls.append(list(cmd))

    svc = ArtifactRefreshService(project_root=ROOT, python_exe="python3", subprocess_runner=fake_run)

    result = svc.refresh_training_artifacts(market="us")

    assert calls == [
        ["python3", "-m", "src.reporting.generate", "--market", "us"],
        ["python3", "scripts/build_dashboard_db.py"],
    ]
    assert result == {"dashboard_db_refreshed": True, "report_rel_path": None}


def test_refresh_backtest_artifacts_can_generate_latest_report():
    calls: list[list[str]] = []

    def fake_run(cmd, *, check):
        calls.append(list(cmd))

    svc = ArtifactRefreshService(
        project_root=ROOT,
        python_exe="python3",
        subprocess_runner=fake_run,
        metadata_db_resolver=lambda _project_root: ROOT / "artifacts" / "metadata.db",
        latest_report_generator=lambda **_kwargs: {"report_rel_path": "reports/backtests/us/latest.html"},
    )

    result = svc.refresh_backtest_artifacts(market="us", refresh_dashboard_db=True)

    assert calls == [["python3", "scripts/build_dashboard_db.py"]]
    assert result == {
        "dashboard_db_refreshed": True,
        "report_rel_path": "reports/backtests/us/latest.html",
    }
