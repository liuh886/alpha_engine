from __future__ import annotations

import pytest

from src.execution.adapter import StrategyExecutionAdapter, build_execution_request


@pytest.mark.parametrize(
    "strategy_class",
    ["BiweeklyTrendStrategy", "VectorizedBiweeklyStrategy"],
)
def test_adapter_executes_biweekly_and_vectorized_configs_with_shared_contract(strategy_class):
    workflow_config = {
        "port_analysis_config": {
            "strategy": {
                "class": strategy_class,
                "kwargs": {
                    "topk": 2,
                    "use_risk_manager": True,
                    "risk_config": {"max_position_weight": 0.2},
                },
            },
        },
    }
    scores = {"AAA": 0.95, "BBB": 0.9, "CCC": 0.85}

    result = StrategyExecutionAdapter(workflow_config).execute(
        asof_date="2026-06-19",
        scores=scores,
        portfolio_positions={"OLD": 0.2},
        cash=10000.0,
        tradable={"AAA": False, "BBB": True, "CCC": True},
    )

    assert result.plan.target_weights == {"BBB": 0.2, "CCC": 0.2}
    assert result.risk_violations == []
    assert {order.instrument for order in result.orders} == {"BBB", "CCC", "OLD"}


def test_adapter_builds_request_from_strategy_profile_position_rule():
    profile_config = {
        "strategy": {
            "rebalance_frequency": "biweekly",
            "position_rule": {"topk": 1, "n_drop": 1},
        },
    }

    request = build_execution_request(
        profile_config,
        asof_date="2026-06-19",
        scores={"AAA": 1.0, "BBB": 0.9},
        tradable={"AAA": True, "BBB": True},
    )

    assert request.config.topk == 1
    assert request.risk_policy.max_position_weight == 0.15
    assert request.signals.scores == {"AAA": 1.0, "BBB": 0.9}
