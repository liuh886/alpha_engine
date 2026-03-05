import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_compile_cmd_includes_profile_when_provided():
    from src.orchestrator import build_compile_cmd

    cmd = build_compile_cmd("python", market="us", profile="configs/strategy_profile_quant_rating_us.json")
    assert cmd[:3] == ["python", "scripts/strategy_to_workflow.py", "--market"]
    assert "--profile" in cmd
    assert "configs/strategy_profile_quant_rating_us.json" in cmd

