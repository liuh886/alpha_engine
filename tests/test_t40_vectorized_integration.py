"""T40.5: Vectorized flag integration tests.

Verify that the ``vectorized`` flag in strategy profiles is correctly
wired through the profile compiler → config → backtest pipeline.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# Profile compiler: vectorized flag → strategy class
# ---------------------------------------------------------------------------

def test_apply_profile_to_config_vectorized_true_sets_class():
    """When strategy.vectorized=true, the config uses VectorizedBiweeklyStrategy."""
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "meta": {"market": "us", "benchmark": "QQQ"},
        "model": {"class": "LGBModel", "feature_pack": "alpha158"},
        "strategy": {
            "rebalance_frequency": "biweekly",
            "min_hold_days": 10,
            "sell_on_ma": 60,
            "sell_rank_threshold": 20,
            "vectorized": True,
            "position_rule": {"topk": 5},
        },
    }
    cfg = apply_profile_to_config(profile, {}, market="us")
    strat = cfg["port_analysis_config"]["strategy"]
    assert strat["class"] == "VectorizedBiweeklyStrategy"
    assert strat["module_path"] == "src.strategies.vectorized_strategy"


def test_apply_profile_to_config_vectorized_false_uses_default():
    """When strategy.vectorized=false, the config uses BiweeklyTrendStrategy."""
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "meta": {"market": "us", "benchmark": "QQQ"},
        "model": {"class": "LGBModel", "feature_pack": "alpha158"},
        "strategy": {
            "rebalance_frequency": "biweekly",
            "min_hold_days": 10,
            "sell_on_ma": 60,
            "sell_rank_threshold": 20,
            "vectorized": False,
            "position_rule": {"topk": 5},
        },
    }
    cfg = apply_profile_to_config(profile, {}, market="us")
    strat = cfg["port_analysis_config"]["strategy"]
    assert strat["class"] == "BiweeklyTrendStrategy"
    assert strat["module_path"] == "src.strategies.biweekly_trend_strategy"


def test_apply_profile_to_config_vectorized_absent_defaults_false():
    """When vectorized flag is absent, the config uses BiweeklyTrendStrategy."""
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "meta": {"market": "us", "benchmark": "QQQ"},
        "model": {"class": "LGBModel", "feature_pack": "alpha158"},
        "strategy": {
            "rebalance_frequency": "biweekly",
            "min_hold_days": 10,
            "sell_on_ma": 60,
            "position_rule": {"topk": 5},
        },
    }
    cfg = apply_profile_to_config(profile, {}, market="us")
    strat = cfg["port_analysis_config"]["strategy"]
    assert strat["class"] == "BiweeklyTrendStrategy"


def test_apply_profile_to_config_vectorized_preserves_kwargs():
    """Vectorized flag does not affect other strategy kwargs propagation."""
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "meta": {"market": "cn", "benchmark": "000300"},
        "model": {"class": "LGBModel", "feature_pack": "alpha158"},
        "strategy": {
            "rebalance_frequency": "biweekly",
            "min_hold_days": 10,
            "sell_on_ma": 60,
            "sell_rank_threshold": 25,
            "vectorized": True,
            "position_rule": {"topk": 8, "n_drop": 3},
            "buy_rule": "score > 0.1",
            "sell_rule": "score < -0.1",
        },
    }
    cfg = apply_profile_to_config(profile, {}, market="cn")
    strat_kwargs = cfg["port_analysis_config"]["strategy"]["kwargs"]
    assert strat_kwargs["topk"] == 8
    assert strat_kwargs["rebalance_steps"] == 10
    assert strat_kwargs["min_hold_days"] == 10
    assert strat_kwargs["sell_ma_window"] == 60
    assert strat_kwargs["sell_rank_threshold"] == 25
    assert strat_kwargs["buy_score_threshold"] == 0.1
    assert strat_kwargs["sell_score_threshold"] == -0.1
    assert "n_drop" not in strat_kwargs


# ---------------------------------------------------------------------------
# Backtest module: vectorized strategy detection
# ---------------------------------------------------------------------------

def test_is_vectorized_strategy_detects_class():
    """_is_vectorized_strategy returns True when class matches."""
    from src.research.backtest import _is_vectorized_strategy

    cfg = {
        "strategy": {
            "class": "VectorizedBiweeklyStrategy",
            "module_path": "src.strategies.vectorized_strategy",
        }
    }
    assert _is_vectorized_strategy(cfg) is True


def test_is_vectorized_strategy_rejects_other_classes():
    """_is_vectorized_strategy returns False for non-vectorized classes."""
    from src.research.backtest import _is_vectorized_strategy

    assert _is_vectorized_strategy({"strategy": {"class": "BiweeklyTrendStrategy"}}) is False
    assert _is_vectorized_strategy({"strategy": {"class": "WeeklyQuantRatingStrategy"}}) is False
    assert _is_vectorized_strategy({}) is False
    assert _is_vectorized_strategy({"strategy": {}}) is False


def test_is_vectorized_strategy_handles_missing_config():
    """_is_vectorized_strategy returns False for empty/missing config."""
    from src.research.backtest import _is_vectorized_strategy

    assert _is_vectorized_strategy({}) is False


# ---------------------------------------------------------------------------
# Profile JSON: vectorized flag presence
# ---------------------------------------------------------------------------

def test_strategy_profile_cn_has_vectorized_flag():
    """CN strategy profile contains the vectorized flag."""
    import json

    profile_path = ROOT / "configs" / "strategy_profile_cn.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert "vectorized" in profile["strategy"]
    assert isinstance(profile["strategy"]["vectorized"], bool)


def test_strategy_profile_us_has_vectorized_flag():
    """US strategy profile contains the vectorized flag."""
    import json

    profile_path = ROOT / "configs" / "strategy_profile_us.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert "vectorized" in profile["strategy"]
    assert isinstance(profile["strategy"]["vectorized"], bool)
