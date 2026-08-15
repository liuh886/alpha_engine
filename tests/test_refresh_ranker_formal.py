from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_ranker_formal import (
    RankerRefreshError,
    _date_identity,
    _annualized_ranker_metrics,
    _cn_signal_metric_metadata,
    _holding_end,
    _latest_realized_holding_end,
    _update_common_metadata,
)


def test_annualized_ranker_metrics_use_non_overlapping_holding_periods() -> None:
    metrics = _annualized_ranker_metrics(
        [
            {"period_return": 0.02, "excess_return": 0.01},
            {"period_return": -0.01, "excess_return": -0.005},
            {"period_return": 0.03, "excess_return": 0.015},
        ],
        holding_sessions=10,
    )

    assert set(metrics) == {
        "Annualized Return",
        "Annualized Volatility",
        "Sharpe Ratio",
        "Information Ratio",
    }
    assert metrics["Annualized Volatility"] > 0.0
    assert metrics["Information Ratio"] > 0.0


def test_cn_x1_2_signal_metrics_keep_frozen_development_scope() -> None:
    metadata = _cn_signal_metric_metadata(
        {
            "date_range": {"start": "2024-01-02", "end": "2026-06-30"},
            "report": [{}] * 57,
            "evidence": {},
        },
        model_id="cn_x1_2",
    )

    assert metadata["rank_ic"]["sample_count"] == 57
    assert metadata["rank_ic"]["scope"] == (
        "frozen development window: 2024-01-02 through 2026-06-30"
    )
    assert metadata["icir"] == metadata["rank_ic"]


def test_date_identity_normalizes_pandas_timestamp() -> None:
    assert _date_identity(pd.Timestamp("2026-07-15")) == "2026-07-15"
    assert _date_identity("2026-07-15 00:00:00") == "2026-07-15"
    accepted_dates = {_date_identity("2026-07-15")}
    assert _date_identity(pd.Timestamp("2026-07-15")) in accepted_dates


def test_date_identity_rejects_missing_value() -> None:
    with pytest.raises(RankerRefreshError, match="invalid date identity"):
        _date_identity(None)


def test_holding_end_includes_execution_delay() -> None:
    calendar = [f"2026-07-{day:02d}" for day in range(1, 20)]

    assert _holding_end(calendar, "2026-07-01") == "2026-07-11"
    assert _holding_end(
        calendar,
        "2026-07-01",
        holding_sessions=10,
        execution_delay_sessions=1,
    ) == "2026-07-12"


def test_latest_realized_holding_end_preserves_accepted_receipt() -> None:
    package = {
        "trace_frequency": "non_overlapping_10_session",
        "portfolio_contract": {
            "cost_bps": 20,
            "holding_sessions": 10,
            "execution_delay_sessions": 1,
        },
        "freshness": {"latest_realized_holding_end": "2026-07-29"},
        "report": [{"date": "2026-07-15"}],
        "positions": [],
        "trades": [],
    }

    assert _latest_realized_holding_end(package) == "2026-07-29"


def test_common_metadata_keeps_realized_end_when_no_new_period_exists(
    tmp_path: Path,
) -> None:
    provider_manifest = tmp_path / "provider.json"
    provider_manifest.write_text(json.dumps({"cutoff": "2026-08-07"}))
    package = {
        "trace_frequency": "non_overlapping_10_session",
        "portfolio_contract": {
            "cost_bps": 20,
            "holding_sessions": 10,
            "execution_delay_sessions": 1,
        },
        "date_range": {"start": "2022-07-01", "end": "2026-08-03"},
        "freshness": {"latest_realized_holding_end": "2026-07-29"},
        "report": [{"date": "2026-07-15"}],
        "positions": [],
        "trades": [],
        "evidence": {},
    }

    _update_common_metadata(
        package,
        cutoff="2026-08-07",
        generated_at="2026-08-09T04:16:42Z",
        provider_manifest=provider_manifest,
        evidence={},
    )

    assert package["evidence_cutoff"] == "2026-08-07"
    assert package["freshness"]["latest_completed_session"] == "2026-08-07"
    assert package["freshness"]["latest_realized_holding_end"] == "2026-07-29"
    assert package["research_only"] is True
    assert package["trade_ready"] is False
    assert package["performance_semantics"]["holding_end_offset_sessions"] == 11
