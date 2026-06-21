from pathlib import Path

from src.assistant.services.report_service import ReportService


class _ReportIndex:
    def __init__(self, row):
        self.row = row

    def get_report(self, report_id):
        return self.row if report_id == "report-1" else None


def _service(project_root: Path, row: dict) -> ReportService:
    return ReportService(
        project_root=project_root,
        report_index=_ReportIndex(row),
        job_service=object(),
    )


def test_resolve_report_file_keeps_paths_inside_project(tmp_path):
    report = tmp_path / "artifacts" / "reports" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<h1>Report</h1>", encoding="utf-8")
    service = _service(tmp_path, {"paths": {"html": "artifacts/reports/report.html"}})

    assert service.resolve_report_file("report-1", "html") == report.resolve()


def test_resolve_report_file_rejects_path_traversal(tmp_path):
    outside = tmp_path.parent / "secret.html"
    service = _service(tmp_path, {"paths": {"html": str(outside)}})

    assert service.resolve_report_file("report-1", "html") is None
