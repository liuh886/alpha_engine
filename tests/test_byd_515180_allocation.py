from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import PROMOTABLE, build_decisions
from src.research.byd_515180_execution import (
    execute_next_common_open,
    run_allocation,
)


def synthetic_common() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=8, freq="B")
    common = pd.DataFrame(
        {
            "common_open_eligible": [True, True, False, True, True, True, True, True],
            "byd_open_return": [0.01, -0.02, 0.03, 0.01, -0.01, 0.02, 0.01, np.nan],
            "etf_open_return": [0.002, 0.003, -0.001, 0.004, 0.001, -0.002, 0.003, np.nan],
        },
        index=index,
    )
    signals = pd.DataFrame(
        {
            "base_byd_weight": [0.75, 0.75, 1.0, 1.0, 0.75, 0.75, 0.75, 1.0],
            "recovery_byd_weight": [0.75, 1.0, 1.0, 1.0, 0.75, 1.0, 0.75, 1.0],
            "recovery_active": [False, True, False, False, False, True, False, False],
            "recovery_branch": ["", "a", "", "", "", "b", "", ""],
        },
        index=index,
    )
    return common, signals


def test_frozen_candidate_family_and_weight_sums() -> None:
    common, signals = synthetic_common()
    decisions = build_decisions(common, signals)
    assert set(PROMOTABLE) == {
        "v1_dividend_75_25",
        "recovery_75_25",
        "recovery_50_50",
    }
    assert set(decisions) == {
        "byd100",
        "etf100",
        "fixed_75_25",
        "byd_v1_cash",
        "v1_dividend_75_25",
        "recovery_75_25",
        "recovery_50_50",
        "binary_100_0",
    }
    for frame in decisions.values():
        assert np.allclose(frame.sum(axis=1), 1.0)
        assert (frame >= 0.0).all().all()


def test_first_overlap_interval_starts_in_cash() -> None:
    common, signals = synthetic_common()
    decision = build_decisions(common, signals)["v1_dividend_75_25"]
    executed = execute_next_common_open(decision, common["common_open_eligible"])
    assert executed.iloc[0].to_dict() == {
        "position_byd_weight": 0.0,
        "position_etf_weight": 0.0,
        "position_cash_weight": 1.0,
    }
    assert executed.iloc[1]["position_byd_weight"] == decision.iloc[0]["byd_weight"]


def test_next_common_open_does_not_advance_on_ineligible_open() -> None:
    common, signals = synthetic_common()
    decision = build_decisions(common, signals)["v1_dividend_75_25"]
    executed = execute_next_common_open(decision, common["common_open_eligible"])
    assert executed.iloc[2].equals(executed.iloc[1])
    assert executed.iloc[3]["position_byd_weight"] == decision.iloc[2]["byd_weight"]


def test_dividend_sleeve_replaces_cash_only_in_v1_defense() -> None:
    common, signals = synthetic_common()
    decisions = build_decisions(common, signals)
    dividend = decisions["v1_dividend_75_25"]
    cash = decisions["byd_v1_cash"]
    defense = signals["base_byd_weight"].eq(0.75)
    assert (dividend.loc[defense, "etf_weight"] == 0.25).all()
    assert (dividend.loc[~defense, "etf_weight"] == 0.0).all()
    assert (cash.loc[defense, "cash_weight"] == 0.25).all()


def test_binary_model_is_present_only_as_diagnostic_contract() -> None:
    assert "binary_100_0" not in PROMOTABLE


def test_cost_charged_on_both_legs_of_rotation() -> None:
    common, signals = synthetic_common()
    decision = build_decisions(common, signals)["v1_dividend_75_25"]
    result = run_allocation("candidate", common, decision, cost_bps=20.0)
    assert (result.daily["turnover_units"] >= 0.0).all()
    assert np.isclose(
        result.daily["cost"], result.daily["turnover_units"] * 0.002
    ).all()


def test_allocation_module_cannot_redefine_execution_engine() -> None:
    source = Path("src/research/byd_515180_allocation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "execute_next_common_open" not in function_names
    assert "run_allocation" not in function_names
