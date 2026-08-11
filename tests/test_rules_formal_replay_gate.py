from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

from src.artifacts.formal_refresh import load_object
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, run_regime_portfolio
from src.research.rules_formal_replay_gate import (
    RulesFormalReplayError,
    assert_exact_formal_prefix,
    verify_cn_frozen_prefix,
)


def _formal_package() -> dict:
    return {
        "portfolio_contract": {"cost_bps": 20},
        "report": [{"date": "2026-07-01", "period_return": 0.01}],
        "positions": [
            {
                "date": "2026-07-01",
                "instrument": "000300",
                "weight": 1.0,
            }
        ],
        "trades": [],
    }


def test_exact_prefix_allows_only_append_only_extension() -> None:
    expected = _formal_package()
    observed = copy.deepcopy(expected)
    observed["report"].append({"date": "2026-07-15", "period_return": 0.02})
    observed["positions"].append(
        {"date": "2026-07-15", "instrument": "000300", "weight": 1.0}
    )

    comparison = assert_exact_formal_prefix(expected, observed, label="fixture")

    assert comparison["exact"] is True


def test_exact_prefix_rejects_historical_mutation() -> None:
    expected = _formal_package()
    observed = copy.deepcopy(expected)
    observed["report"][0]["period_return"] = 0.02

    with pytest.raises(RulesFormalReplayError, match="exact replay mismatch"):
        assert_exact_formal_prefix(expected, observed, label="fixture")


def test_cn_regime_portfolio_respects_continuation_weights() -> None:
    date = pd.Timestamp("2026-07-01")
    ledger = pd.DataFrame(
        [
            {
                "window": "2026H2_PARTIAL",
                "datetime": date,
                "instrument": "000001",
            }
        ]
    )
    benchmark_returns = pd.Series([0.01], index=pd.DatetimeIndex([date]))
    state = pd.DataFrame(
        [
            {
                "long_trend": False,
                "medium_momentum": False,
                "breadth_value": 0.0,
                "cross_sectional_breadth": False,
                "votes": 0,
            }
        ],
        index=pd.DatetimeIndex([date]),
    )
    spec = RegimeGateSpec()

    _, periods, holdings, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=("2026H2_PARTIAL",),
        variant=spec.variant(),
        cost_bps=20,
        initial_weights={"000300": 1.0},
    )

    assert periods.iloc[0]["turnover"] == 0.0
    assert periods.iloc[0]["cost"] == 0.0
    assert periods.iloc[0]["net_return"] == pytest.approx(0.01)
    assert holdings.iloc[0]["instrument"] == "000300"


def test_committed_cn_frozen_trace_is_exact_prefix_of_current_formal() -> None:
    package = load_object(Path("data/research/formal_backtests/cn_x1_1.json"))

    receipt = verify_cn_frozen_prefix(Path.cwd(), package)

    assert receipt["decision"] == "exact_replay"
    assert receipt["trace_reproduction"]["exact"] is True
