import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from src.assistant.report_index import ReportIndex
from src.reporting.report_archive import export_reports_zip


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "artifacts" / "archives" / "reports").mkdir(parents=True)
        (root / "reports").mkdir()
        db_path = root / "metadata.db"
        yield root, db_path


def test_report_export_flow(workspace):
    root, db_path = workspace
    idx = ReportIndex(db_path=db_path)

    # 1. Create some dummy reports on disk
    report1_rel = "reports/backtest_1.html"
    report2_rel = "reports/arena_1.html"
    (root / report1_rel).write_text("backtest report content")
    (root / report2_rel).write_text("arena report content")

    # 2. Index them
    idx.upsert(
        report_type="backtest",
        ref_id="run_1",
        date="2025-01-01",
        formats=["html"],
        paths={"html": report1_rel},
    )
    idx.upsert(
        report_type="arena_daily",
        ref_id="arena_us",
        date="2025-01-01",
        formats=["html"],
        paths={"html": report2_rel},
    )

    # 3. Export all
    res = export_reports_zip(project_root=root, db_path=db_path, type_filter="all", limit=10)

    assert res["ok"] is True
    assert res["included_reports"] == 2

    zip_path = Path(res["output_path"])
    assert zip_path.exists()

    # 4. Verify zip content
    with zipfile.ZipFile(zip_path, "r") as zf:
        file_list = zf.namelist()
        assert "manifest.json" in file_list
        assert report1_rel in file_list
        assert report2_rel in file_list

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert len(manifest["reports"]) == 2

    # 5. Verify the export itself is indexed
    archives = idx.list_reports(report_type="archive")
    assert len(archives) == 1
    assert archives[0]["ref_id"] == "reports:all"
    assert "zip" in json.loads(archives[0]["paths_json"])
