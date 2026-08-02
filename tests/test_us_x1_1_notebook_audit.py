from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.research.us_x1_1_notebook_audit import (
    BASE_COST_BPS,
    EXPECTED_PARAMETER_IDENTITY,
    EXPECTED_PROVIDER_IDENTITY,
    TOPK,
    WINDOWS,
    _compound,
    _max_drawdown,
    _security_summary,
    _window_summary,
)


def test_registered_contract_is_frozen() -> None:
    assert WINDOWS == ("2024H1", "2024H2", "2025H1", "2025H2")
    assert TOPK == 15
    assert BASE_COST_BPS == 20
    assert len(EXPECTED_PROVIDER_IDENTITY) == 64
    assert len(EXPECTED_PARAMETER_IDENTITY) == 64


def test_compound_and_drawdown_include_initial_equity() -> None:
    returns = pd.Series([-0.10, 0.20, -0.05])
    assert abs(_compound(returns) - (0.9 * 1.2 * 0.95 - 1.0)) < 1e-12
    assert abs(_max_drawdown(returns) - (-0.10)) < 1e-12


def test_window_summary_separates_gross_cost_and_net() -> None:
    periods = pd.DataFrame(
        {
            "window": ["2024H1", "2024H1"],
            "gross_return": [0.10, 0.05],
            "net_return": [0.09, 0.04],
            "qqq_return": [0.02, 0.01],
            "turnover": [0.5, 0.4],
            "transaction_cost": [0.01, 0.01],
        }
    )
    result = _window_summary(periods).iloc[0]
    expected_gross = 1.10 * 1.05 - 1.0
    expected_net = 1.09 * 1.04 - 1.0
    assert abs(result["gross_selection_return"] - expected_gross) < 1e-12
    assert abs(result["net_strategy_return"] - expected_net) < 1e-12
    assert abs(result["transaction_cost_drag"] - (expected_gross - expected_net)) < 1e-12
    assert result["turnover"] == 0.9


def test_security_summary_reconciles_exit_costs() -> None:
    attribution = pd.DataFrame(
        {
            "instrument": ["A", "B"],
            "period_index": [1, 1],
            "window": ["2024H1", "2024H1"],
            "gross_contribution": [0.03, -0.01],
            "allocated_transaction_cost": [0.001, 0.001],
            "forward_return": [0.06, -0.02],
            "rank": [1, 2],
        }
    )
    trades = pd.DataFrame(
        {
            "instrument": ["A", "B", "C"],
            "allocated_transaction_cost": [0.001, 0.001, 0.002],
        }
    )
    result = _security_summary(attribution, trades).set_index("instrument")
    assert abs(result.loc["A", "net_contribution"] - 0.029) < 1e-12
    assert abs(result.loc["B", "net_contribution"] + 0.011) < 1e-12
    assert abs(result.loc["C", "net_contribution"] + 0.002) < 1e-12


def test_complete_notebook_contract() -> None:
    path = Path("notebooks/models/us_x1_1_complete_backtest.ipynb")
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload["metadata"]["alpha_engine"]
    assert metadata["model_id"] == "us_x1_1"
    assert metadata["notebook_role"] == "complete_backtest_audit"
    assert metadata["research_only"] is True
    assert metadata["trade_ready"] is False
    assert metadata["provider_artifact_id"] == 8831837784
    assert metadata["reproduction_artifact_id"] == 8831960659
    source = "\n".join(
        "".join(cell.get("source", []))
        if isinstance(cell.get("source"), list)
        else str(cell.get("source", ""))
        for cell in payload["cells"]
    )
    for required in (
        "daily_signals",
        "rebalance_signals",
        "trade_ledger.csv",
        "holdings.csv",
        "security_attribution.csv",
        "US_X1_1_REFIT",
        "complete_backtest_reproduced",
    ):
        assert required in source
