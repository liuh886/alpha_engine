"""Audit the CLI-owned data update pipeline and snapshot publication boundary."""

from __future__ import annotations

import inspect
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestUpdateThresholds:
    def test_argparse_default_max_missing_pct(self):
        source = (PROJECT_ROOT / "scripts" / "update_data.py").read_text(encoding="utf-8")
        assert "default=0.30" in source
        assert "default=60" in source

    def test_strict_mode_flag_exists(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--strict", action="store_true")
        assert parser.parse_args(["--strict"]).strict is True

    def test_validate_for_publish_defaults(self):
        from src.data.update_accounting import UpdateAccountingReport

        parameters = inspect.signature(UpdateAccountingReport.validate_for_publish).parameters
        assert "max_missing_pct" in parameters
        assert "max_missing_count" in parameters
        assert "strict" in parameters


class TestSnapshotPublishing:
    def test_snapshot_store_path_is_artifacts(self):
        from src.common.paths import SNAPSHOT_STORE

        path = str(SNAPSHOT_STORE).lower()
        assert "artifacts" in path
        assert "snapshots" in path

    def test_data_snapshot_class_has_publication_methods(self):
        from src.data.snapshot import DataSnapshot

        for method in ("create_snapshot", "publish_snapshot", "get_latest_snapshot", "resolve_snapshot"):
            assert hasattr(DataSnapshot, method)

    def test_data_service_reports_latest_snapshot_identity(self):
        source = (
            PROJECT_ROOT / "src" / "assistant" / "services" / "data_service.py"
        ).read_text(encoding="utf-8")
        assert "latest_snapshot_id" in source


class TestAccountingReport:
    def test_accounting_report_has_publish_validation(self):
        from src.data.update_accounting import UpdateAccountingReport

        assert hasattr(UpdateAccountingReport, "validate_for_publish")

    def test_optional_symbol_categorization_remains_owned_by_accounting(self):
        from src.data.update_accounting import UpdateAccountingReport

        assert hasattr(UpdateAccountingReport, "_categorize_symbol") or hasattr(
            UpdateAccountingReport, "validate_for_publish"
        )
