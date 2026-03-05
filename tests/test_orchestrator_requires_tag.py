import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_run_requires_tag_for_single_market(monkeypatch):
    from src.orchestrator import Orchestrator

    orch = Orchestrator()
    try:
        orch.run(market="us", model_type="lgbm", profile="configs/strategy_profile.json", tag="")
    except ValueError as e:
        assert "tag" in str(e).lower()
    else:
        raise AssertionError("expected ValueError when tag is missing")


def test_run_requires_tag_for_all_market(monkeypatch):
    from src.orchestrator import Orchestrator

    orch = Orchestrator()
    try:
        orch.run(market="all", model_type="lgbm", profile="", tag="")
    except ValueError as e:
        assert "tag" in str(e).lower()
    else:
        raise AssertionError("expected ValueError when tag is missing for all markets")
