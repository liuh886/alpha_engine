import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_format_run_name_prefers_model_tag_over_strategy_name():
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    strategy_profile = {"meta": {"name": "LGBM_v1"}}
    params = {"model_tag": "LGBM_v2_custom"}

    out = g["format_run_name"]("us", "2026-02-05 10:00", "abcdef1234", params, strategy_profile)
    assert out.startswith("[US] LGBM_v2_custom 2026-02-05 10:00")


def test_format_run_name_falls_back_to_strategy_name():
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    strategy_profile = {"meta": {"name": "LGBM_v1"}}
    params = {}

    out = g["format_run_name"]("us", "2026-02-05 10:00", "abcdef1234", params, strategy_profile)
    assert out.startswith("[US] LGBM_v1 2026-02-05 10:00")

