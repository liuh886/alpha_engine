from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_22_intraday_rank_pilot_runtime import (
    _audit_frame,
    _enrich_ledger,
    _full_path_frame,
)


def test_full_path_frame_uses_declared_interval_not_last_state2_date():
    index = pd.bdate_range("2024-08-05", "2024-08-16")
    baseline = pd.DataFrame(
        {"net_return": 0.001, "turnover_units": 0.0}, index=index
    )
    state2 = pd.DataFrame(
        {"delever_to_qqq_net_advantage": [0.01]}, index=index[[2]]
    )
    contract = {
        "intraday_data": {
            "start_date": "2024-08-05",
            "end_date": "2024-08-16",
        }
    }
    baseline_slice, path_frame = _full_path_frame(
        baseline, state2, contract
    )
    assert baseline_slice.index.min() == index.min()
    assert baseline_slice.index.max() == index.max()
    assert len(path_frame) == len(index)
    assert path_frame.loc[index[2], "delever_to_qqq_net_advantage"] == 0.01
    assert path_frame["delever_to_qqq_net_advantage"].notna().sum() == 1


def test_event_audit_attaches_prices_and_exact_cost_components():
    index = pd.DatetimeIndex(["2025-07-10"])
    frame = pd.DataFrame(
        {
            "QQQ_open": [100.0],
            "QQQ_opening_close": [101.0],
            "QQQ_next_open": [102.0],
            "TQQQ_open": [50.0],
            "TQQQ_opening_close": [51.0],
            "TQQQ_next_open": [52.0],
            "SPY_open": [600.0],
            "SPY_opening_close": [601.0],
            "SPY_next_open": [602.0],
            "baseline_exact_gross_return": [0.02],
            "overlay_exact_gross_return": [0.01],
            "baseline_exact_net_return": [0.0199],
            "overlay_exact_net_return": [0.0097],
            "switch_turnover_units": [1.5],
            "baseline_next_reconcile_turnover_units": [0.1],
            "overlay_next_reconcile_turnover_units": [1.5],
            "incremental_turnover_units": [2.9],
        },
        index=index,
    )
    contract = {
        "boundaries": {
            "transaction_cost_bps_per_turnover_unit": 10.0
        }
    }
    audited = _audit_frame(frame, contract)
    assert audited.loc[index[0], "switch_cost"] == pytest.approx(0.0015)
    assert audited.loc[
        index[0], "baseline_next_reconcile_cost"
    ] == pytest.approx(0.0001)
    assert audited.loc[
        index[0], "overlay_next_reconcile_cost"
    ] == pytest.approx(0.0015)
    assert audited.loc[index[0], "incremental_cost"] == pytest.approx(0.0029)

    ledger = pd.DataFrame(
        {"score": [0.8], "trigger": [True]}, index=index
    )
    enriched = _enrich_ledger(ledger, audited)
    assert enriched.loc[index[0], "QQQ_open"] == 100.0
    assert enriched.loc[index[0], "TQQQ_next_open"] == 52.0
    assert enriched.loc[index[0], "incremental_cost"] == pytest.approx(0.0029)
