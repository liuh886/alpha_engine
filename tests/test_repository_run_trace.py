from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.research.notebook_experiment_api import run_10d_experiment


@dataclass(frozen=True)
class _Config:
    market: str = "us"
    benchmark: str = "QQQ"
    topk: int = 2
    rebalance_days: int = 10
    experiment_id: str = "trace_contract_test"

    def to_dict(self):
        return asdict(self)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2025-01-02", periods=30)
    symbols = ["AAA", "BBB", "CCC"]
    index = pd.MultiIndex.from_product(
        [dates, symbols], names=["datetime", "instrument"]
    )
    score_values = []
    return_values = []
    for date_index, _ in enumerate(dates):
        for symbol_index, _ in enumerate(symbols):
            score_values.append(float(symbol_index + date_index / 100.0))
            return_values.append(0.01 * (symbol_index + 1) - 0.0001 * date_index)
    predictions = pd.DataFrame({"score": score_values}, index=index)
    returns = pd.DataFrame({"return": return_values}, index=index)
    returns.attrs.update({"provenance": "raw_forward_return", "horizon": 10})
    benchmark = pd.DataFrame(
        {"return": np.full(len(dates), 0.005)}, index=dates
    )
    return predictions, returns, benchmark


def test_experiment_retains_exact_period_trace_holdings_and_contributions() -> None:
    predictions, returns, benchmark = _frames()

    payload = run_10d_experiment(
        config=_Config(),
        candidates={"xgb:daily_ranker:test": predictions},
        raw_returns=returns,
        benchmark_returns=benchmark,
    )

    assert payload["schema_version"] == "1.1"
    assert payload["trace_contract"]["daily_nav_claim"] is False
    traces = payload["backtest_traces"]
    assert len(traces) == 2
    original = next(item for item in traces if item["orientation"] == "original")
    assert original["trace_frequency"] == "non_overlapping_forward_horizon"
    assert len(original["points"]) == 3
    assert len(original["holdings"]) == 3
    assert len(original["name_contributions"]) == 3
    assert original["points"][0]["nav_after_forward_horizon"] > 1.0
    assert set(original["holdings"][0]["weights"]) == {"BBB", "CCC"}
    assert original["research_only"] is True
    assert original["trade_ready"] is False
