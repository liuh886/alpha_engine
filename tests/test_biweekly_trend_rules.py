import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_is_rebalance_day_every_10_steps():
    from src.strategies.biweekly_trend_rules import is_rebalance_day

    assert is_rebalance_day(0, 10)
    assert not is_rebalance_day(1, 10)
    assert is_rebalance_day(10, 10)


def test_can_sell_min_hold_calendar_days():
    from src.strategies.biweekly_trend_rules import can_sell

    entry = date(2025, 1, 1)
    assert not can_sell(entry, date(2025, 1, 10), 10)  # 9 days elapsed
    assert can_sell(entry, date(2025, 1, 11), 10)  # 10 days elapsed


def test_strategy_class_loadable():
    from src.strategies.biweekly_trend_strategy import BiweeklyTrendStrategy

    assert BiweeklyTrendStrategy is not None


def test_strategy_profile_has_biweekly_rules():
    import json

    profile_path = ROOT / "configs" / "strategy_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    strategy = profile.get("strategy", {})
    assert strategy.get("rebalance_frequency") == "biweekly"
    assert strategy.get("min_hold_days") == 10
    assert strategy.get("sell_on_ma") == 60
    assert strategy.get("sell_rank_threshold") == 20


def test_biweekly_strategy_removes_n_drop():
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "strategy": {
            "position_rule": {"topk": 5, "n_drop": 5},
            "rebalance_frequency": "biweekly",
        }
    }
    cfg = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {}}}}},
        "port_analysis_config": {"strategy": {"kwargs": {}}},
    }

    updated = apply_profile_to_config(profile, cfg, "us")
    strat = updated["port_analysis_config"]["strategy"]
    strat_kwargs = strat.get("kwargs", {})
    assert strat.get("class") == "BiweeklyTrendStrategy"
    assert "n_drop" not in strat_kwargs
