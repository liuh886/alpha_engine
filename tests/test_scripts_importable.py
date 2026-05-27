import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_script_without_project_root(script_name: str) -> None:
    scripts_dir = str(ROOT / "scripts")
    original = list(sys.path)
    try:
        sys.path = [scripts_dir] + [p for p in original if str(p).lower() != str(ROOT).lower()]
        runpy.run_path(str(ROOT / "scripts" / script_name), run_name="not_main")
    finally:
        sys.path = original


def test_extract_backtest_sample_script_imports_without_project_root():
    _run_script_without_project_root("build_dashboard_db.py")
