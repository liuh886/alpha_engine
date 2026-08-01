from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_qqqi_vxn_bridge_v4_2_prospective_monitor import (
    _prospective_allocation_differences,
)


def _daily(*, bridge: bool) -> pd.DataFrame:
    index = pd.bdate_range("2026-07-31", periods=3)
    qqqi_weight = [1.0, 0.5 if bridge else 0.0, 0.0]
    qqq_weight = [0.0, 0.5 if bridge else 1.0, 0.25]
    return pd.DataFrame(
        {
            "position_state": [0, 1, 2],
            "position_label": ["defensive", "attack", "partial_leverage"],
            "weight_QQQI": qqqi_weight,
            "weight_QQQ": qqq_weight,
            "weight_TQQQ": [0.0, 0.0, 0.75],
            "gross_return": [0.0, 0.01 if bridge else 0.012, 0.02],
            "turnover_units": [1.0, 1.0 if bridge else 2.0, 1.5],
            "transaction_cost": [0.001, 0.001 if bridge else 0.002, 0.0015],
            "net_return": [0.0, 0.009 if bridge else 0.010, 0.0185],
        },
        index=index,
    )


def test_monitor_keeps_only_prospective_rows_and_computes_deltas() -> None:
    differences = _prospective_allocation_differences(
        _daily(bridge=False),
        _daily(bridge=True),
        "2026-08-01",
    )
    assert len(differences) == 2
    first = differences.iloc[0]
    assert first["position_state"] == 1
    assert first["baseline_weight_QQQ"] == 1.0
    assert first["bridge_weight_QQQ"] == 0.5
    assert first["turnover_units_delta"] == -1.0
    assert first["transaction_cost_delta"] == -0.001
    assert first["net_return_delta"] == -0.001


def test_monitor_rejects_divergent_state_traces() -> None:
    baseline = _daily(bridge=False)
    bridge = _daily(bridge=True)
    bridge.loc[bridge.index[-1], "position_state"] = 1
    with pytest.raises(AssertionError, match="state traces diverged"):
        _prospective_allocation_differences(
            baseline,
            bridge,
            "2026-08-01",
        )
