from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path
from typing import Callable

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

class ArtifactRefreshService:
    def __init__(
        self,
        *,
        project_root: str | Path,
        python_exe: str,
        subprocess_runner: Callable[..., object] | None = None,
        metadata_db_resolver: Callable[[Path], Path] | None = None,
        latest_report_generator: Callable[..., dict] | None = None,
        printer: Callable[[str], None] = print,
    ):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)
        self._subprocess_runner = subprocess_runner or subprocess.run
        self._printer = printer

        if metadata_db_resolver is None:
            from src.assistant.metadata_db import resolve_metadata_db_path
            metadata_db_resolver = resolve_metadata_db_path
            
        if latest_report_generator is None:
            from src.reporting.backtest_report import generate_latest_backtest_report
            latest_report_generator = generate_latest_backtest_report

        self._metadata_db_resolver = metadata_db_resolver
        self._latest_report_generator = latest_report_generator

    def refresh_training_artifacts(self, *, market: str) -> dict[str, str | bool | None]:
        """
        Refresh reports and dashboard DB after training.
        Switched to in-process calls for reliability and speed.
        """
        self._printer(f"Refreshing training artifacts for {market} (In-process)...")
        
        try:
            from src.reporting.generate import generate_report
            generate_report(market)
        except Exception as e:
            self._printer(f"Warning: Failed in-process report generation: {e}. Falling back to subprocess...")
            self._subprocess_runner(
                [self._python_exe, "-m", "src.reporting.generate", "--market", market],
                check=True,
            )

        try:
            from scripts.build_dashboard_db import build_db
            build_db()
        except Exception as e:
            self._printer(f"Warning: Failed in-process dashboard DB build: {e}. Falling back to subprocess...")
            self._subprocess_runner([self._python_exe, "scripts/build_dashboard_db.py"], check=True)
            
        return {"dashboard_db_refreshed": True, "report_rel_path": None}

    def refresh_backtest_artifacts(
        self,
        *,
        market: str,
        refresh_dashboard_db: bool,
    ) -> dict[str, str | bool | None]:
        """
        Refresh dashboard DB and generate latest backtest report.
        """
        if refresh_dashboard_db:
            try:
                from scripts.build_dashboard_db import build_db
                build_db()
            except Exception as e:
                self._printer(f"Warning: Failed in-process dashboard DB build: {e}. Falling back to subprocess...")
                self._subprocess_runner([self._python_exe, "scripts/build_dashboard_db.py"], check=True)

        report_rel_path = None
        try:
            report = self._latest_report_generator(
                market=market,
                project_root=self._project_root,
                db_path=self._metadata_db_resolver(self._project_root),
            )
            report_rel_path = str(report.get("report_rel_path") or "") or None
            if report_rel_path:
                self._printer(f"Backtest report: /{report_rel_path.lstrip('/')}")
        except Exception as exc:
            self._printer(f"Warning: Failed to generate backtest report: {exc}")

        return {
            "dashboard_db_refreshed": bool(refresh_dashboard_db),
            "report_rel_path": report_rel_path,
        }
