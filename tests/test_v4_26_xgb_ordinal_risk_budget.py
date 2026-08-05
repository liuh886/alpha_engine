from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_qqqi_v4_26_xgb_ordinal_risk_budget import _effective_contract
from src.research.v4_24_xgb_adjacent_path_data import STATE_ORDER
from src.research.v4_26_xgb_ordinal_risk_budget import (
    _add_oracle_label,
    _attach_predictions,
)

CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_ordinal_risk_budget_v4_26_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _row() -> dict:
    row: dict[str, float | str | pd.Timestamp] = {
        "decision_date": pd.Timestamp("2020-01-02"),
        "baseline_path_utility": 0.01,
    }
    for index, state in enumerate(STATE_ORDER):
        row[f"{state}_path_utility"] = float(index) / 100.0
        row[f"{state}_terminal_return"] = float(index) / 100.0
        row[f"{state}_mae"] = 0.0
    return row


def test_contract_is_one_fixed_multiclass_convergence_model() -> None:
    contract = _contract()
    assert contract["model"]["objective"] == "multi:softprob"
    assert contract["model"]["num_class"] == 4
    assert contract["model"]["parameter_search_allowed"] is False
    assert contract["model"]["feature_selection_allowed"] is False
    assert contract["features"]["total_inputs"] == 35
    assert contract["decision"]["posterior_rule"] == (
        "expected_state_index_round_half_up"
    )
    assert contract["boundaries"]["no_v4_27_without_new_information"] is True


def test_oracle_tie_breaks_toward_lower_risk_state() -> None:
    row = _row()
    row["defense_path_utility"] = 0.04
    row["bridge_path_utility"] = 0.04
    row["core_path_utility"] = 0.03
    row["leveraged_path_utility"] = 0.02
    labeled = _add_oracle_label(pd.DataFrame([row]))
    assert int(labeled.loc[0, "oracle_state_index"]) == 0
    assert labeled.loc[0, "oracle_state"] == "defense"


def test_posterior_expected_risk_uses_half_up_rounding() -> None:
    row = _row()
    frame = pd.DataFrame([row, {**row, "decision_date": pd.Timestamp("2020-01-16")}])
    probabilities = np.asarray(
        [
            [0.50, 0.50, 0.00, 0.00],  # expected 0.5 -> bridge
            [0.00, 0.50, 0.50, 0.00],  # expected 1.5 -> core
        ],
        dtype=float,
    )
    scored = _attach_predictions(frame, probabilities)
    assert scored["selected_state"].tolist() == ["bridge", "core"]
    assert scored["selected_state_index"].tolist() == [1, 2]


def test_runtime_compatibility_edges_are_inherited_only_for_data_builder() -> None:
    contract = _effective_contract(_contract())
    edges = contract["states"]["edges"]
    assert [edge["edge"] for edge in edges] == [
        "defense_vs_bridge",
        "bridge_vs_core",
        "core_vs_leveraged",
    ]
    assert contract["model"]["objective"] == "multi:softprob"
