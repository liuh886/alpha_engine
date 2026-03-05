import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_server_uses_job_service_not_in_memory_dict():
    scripts_dir = str(ROOT / "scripts")
    original = list(sys.path)
    try:
        sys.path = [scripts_dir] + [p for p in original if str(p).lower() != str(ROOT).lower()]
        g = runpy.run_path(str(ROOT / "scripts" / "dashboard_server.py"), run_name="not_main")
    finally:
        sys.path = original

    assert "JOBS" not in g, "dashboard_server.py should not rely on a global in-memory JOBS dict"
    assert "_get_job_service" in g, "dashboard_server.py should expose a lazy JobService accessor"

