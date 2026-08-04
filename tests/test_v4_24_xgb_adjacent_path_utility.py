from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_24_xgb_adjacent_path_data import (
    EDGE_ORDER,
    STATE_FEATURES,
    STATE_ORDER,
    _feature_schema,
    _normalised_weights,
    _path_statistics,
)
from src.research.v4_24_xgb_adjacent_path_model import (
    embargo_train_end,
    select_ordinal_state,
)

CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_adjacent_path_utility_v4_24_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_contract_has_four_ordered_states_and_no_action_descriptors() -> None:
    contract = _contract()
    assert tuple(contract["states"]["order"]) == STATE_ORDER
    assert tuple(item["edge"] for item in contract["states"]["edges"]) == EDGE_ORDER
    market, credit, features = _feature_schema(contract)
    assert len(market) == 21
    assert len(credit) == 8
    assert tuple(contract["features"]["state_context"]) == STATE_FEATURES
    assert len(features) == 35
    assert all("candidate_" not in feature for feature in features)
    weights = _normalised_weights(contract)
    assert set(weights) == set(STATE_ORDER)
    assert all(np.isclose(value.sum(), 1.0) for value in weights.values())


def test_path_utility_includes_entry_exit_cost_and_mae_penalty() -> None:
    contract = _contract()
    result = _path_statistics(
        pd.Series([0.01, -0.02, 0.03]),
        entry_turnover=1.0,
        exit_turnover=0.5,
        cost_rate=0.001,
        mae_penalty=float(contract["decision"]["mae_penalty"]),
    )
    net = np.asarray([0.009, -0.02, 0.0295])
    cumulative = np.cumprod(1.0 + net) - 1.0
    expected_terminal = float(cumulative[-1])
    expected_mae = float(min(0.0, cumulative.min()))
    assert np.isclose(result["terminal_return"], expected_terminal)
    assert np.isclose(result["mae"], expected_mae)
    assert np.isclose(
        result["path_utility"], expected_terminal + 0.50 * expected_mae
    )


def test_ten_session_embargo_excludes_immediately_preceding_grid_row() -> None:
    index = pd.bdate_range("2015-01-02", periods=20, freq="10B")
    test_start = index[10]
    result = embargo_train_end(
        index,
        test_start,
        index[9],
        embargo_sessions=10,
        sample_every_sessions=10,
    )
    assert result == index[8]
    assert index[9] > result


def test_ordinal_policy_traverses_only_adjacent_edges() -> None:
    contract = _contract()
    base = {
        "fold": "fold",
        "baseline_path_utility": 0.0,
        "baseline_terminal_return": 0.0,
        "baseline_mae": 0.0,
    }
    for state, utility in zip(STATE_ORDER, [0.01, 0.02, 0.03, 0.04]):
        base[f"{state}_path_utility"] = utility
        base[f"{state}_terminal_return"] = utility
        base[f"{state}_mae"] = 0.0
    rows = []
    probabilities = [
        (0.49, 0.99, 0.99),
        (0.51, 0.49, 0.99),
        (0.51, 0.51, 0.49),
        (0.51, 0.51, 0.51),
    ]
    for number, values in enumerate(probabilities):
        row = dict(base)
        row["decision_date"] = pd.Timestamp("2020-01-02") + pd.Timedelta(days=number)
        for edge, value in zip(EDGE_ORDER, values):
            row[f"prob_{edge}"] = value
        rows.append(row)
    selected = select_ordinal_state(pd.DataFrame(rows), contract)
    assert selected["selected_state"].tolist() == list(STATE_ORDER)
    assert selected["selected_top_two"].tolist() == [False, False, True, True]


def test_ordinal_policy_does_not_skip_a_failed_lower_edge() -> None:
    contract = _contract()
    row = {
        "decision_date": pd.Timestamp("2020-01-02"),
        "fold": "fold",
        "baseline_path_utility": 0.0,
        "baseline_terminal_return": 0.0,
        "baseline_mae": 0.0,
        "prob_defense_vs_bridge": 0.49,
        "prob_bridge_vs_core": 0.99,
        "prob_core_vs_leveraged": 0.99,
    }
    for state, utility in zip(STATE_ORDER, [0.0, 0.01, 0.02, 0.03]):
        row[f"{state}_path_utility"] = utility
        row[f"{state}_terminal_return"] = utility
        row[f"{state}_mae"] = 0.0
    selected = select_ordinal_state(pd.DataFrame([row]), contract)
    assert selected.loc[0, "selected_state"] == "defense"
    assert selected.loc[0, "edge_trace"].count("|") == 0
