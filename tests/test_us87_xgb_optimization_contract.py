from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "configs/research_paradigms/us_10d_xgb_optimization_dev_v1.yaml"
SCRIPT = ROOT / "scripts/run_us87_xgb_optimization.py"


def _load_runner() -> ModuleType:
    name = "us87_xgb_optimization_runner"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_us_grid_is_bounded_and_excludes_challenge() -> None:
    payload = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert payload["market"] == "us"
    assert payload["candidate_grid"]["ranker"]["model_families"] == ["xgb"]
    assert len(payload["factor_library"]["groups"]) == 2
    assert len(payload["candidate_grid"]["ranker"]["calibrations"]) == 3
    assert payload["walk_forward"]["test_end"] == "2025-12-31"
    assert payload["walk_forward"]["last_test_year"] == 2025
    assert payload["strategy"]["top_n"] == 15


def test_us_selection_penalizes_tail_risk() -> None:
    module = _load_runner()
    safer = {
        "excess_return": 0.10,
        "max_drawdown": -0.10,
        "icir": 0.10,
        "rank_ic": 0.02,
    }
    baseline = {
        "excess_return": 0.09,
        "max_drawdown": -0.20,
        "icir": 0.10,
        "rank_ic": 0.02,
    }
    assert module._decision(safer, baseline) == "improvement_supported"


def test_us_challenge_requires_signal_alignment() -> None:
    module = _load_runner()
    selected = {
        "excess_return": 0.20,
        "max_drawdown": -0.10,
        "icir": -0.01,
        "rank_ic": 0.02,
    }
    baseline = {
        "excess_return": 0.10,
        "max_drawdown": -0.15,
        "icir": 0.10,
        "rank_ic": 0.02,
    }
    assert module._decision(selected, baseline) == "baseline_only"
