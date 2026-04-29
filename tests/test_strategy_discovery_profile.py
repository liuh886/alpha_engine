import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from qlib.contrib.data.loader import Alpha158DL

from scripts.extract_backtest_sample import load_workflow_meta
from src.workflows.profile_compiler import apply_profile_to_config


def test_profile_compiles_discovery_defaults():
    profile = {
        "meta": {"benchmark": "QQQ", "benchmark_by_market": {"cn": "000300", "us": "QQQ"}},
        "model": {
            "class": "LGBModel",
            "feature_pack": "alpha158",
            "extra_features": [
                "$close/Ref($close, 5)-1",
                "$close/Ref($close, 10)-1",
                "$close/Ref($close, 20)-1",
                "Std($close, 10)",
                "$volume/Ref($volume, 10)-1",
            ],
            "label": ["Ref($close, -10) / Ref($close, -1) - 1"],
            "train_window": {
                "train": ["2021-01-01", "2024-12-31"],
                "valid": ["2025-01-01", "2025-12-31"],
                "test": ["2025-01-01", "2025-12-31"],
            },
        },
        "strategy": {
            "position_rule": {"topk": 5, "n_drop": 5},
            "costs_bps": 10,
            "capital": 10000,
            "backtest_window": ["2025-01-01", "2025-12-31"],
        },
    }
    base = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {"label": ["old_label"]}}}}},
        "port_analysis_config": {"strategy": {"kwargs": {}}, "backtest": {}},
    }
    cfg = apply_profile_to_config(profile, base, "us")

    handler = cfg["task"]["dataset"]["kwargs"]["handler"]
    assert handler.get("class") == "DataHandlerLP"
    assert "extra_features" not in handler.get("kwargs", {})
    assert "label" not in handler.get("kwargs", {})
    data_loader = handler["kwargs"]["data_loader"]
    loader_cfg = data_loader["kwargs"]["config"]
    features = loader_cfg["feature"]
    labels = loader_cfg["label"]
    assert labels == ["Ref($close, -10) / Ref($close, -1) - 1"]
    for feat in profile["model"]["extra_features"]:
        assert feat in features
    alpha_features = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )[0]
    assert len(features) >= len(alpha_features) + len(profile["model"]["extra_features"])

    strat = cfg["port_analysis_config"]["strategy"]["kwargs"]
    assert strat["topk"] == 5
    assert strat["n_drop"] == 5
    assert cfg["port_analysis_config"]["backtest"]["start_time"] == "2025-01-01"


def test_profile_uses_market_benchmark_override():
    profile = {"meta": {"benchmark_by_market": {"cn": "000300", "us": "QQQ"}}}
    base = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {}}}}},
        "port_analysis_config": {"strategy": {"kwargs": {}}, "backtest": {}},
    }
    cfg = apply_profile_to_config(profile, base, "cn")
    assert cfg.get("benchmark") == "000300"


def test_workflow_meta_includes_alpha158_fields():
    meta = load_workflow_meta("us", "lgbm")
    assert meta.get("benchmark") == "QQQ"
    assert meta.get("label") == ["Ref($close, -10) / Ref($close, -1) - 1"]
    assert "$close/Ref($close, 10)-1" in (meta.get("features") or [])
