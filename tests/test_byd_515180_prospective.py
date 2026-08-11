from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.byd_515180_prospective import (
    SCHEMA_VERSION,
    _json_bytes,
    _observation_frame,
    build_paired_observations,
    execute_next_common_open,
    persist_store,
    strategy_daily,
)
from src.research.byd_prospective_shadow import (
    ChainLinkedExtension,
    IndependentAudit,
)


def _paired(date: str, target: float, *, eligible: bool = True) -> dict:
    etf_weight = 1.0 - target
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "paired_observation",
        "signal_date": date,
        "observed_at_utc": f"{date}T10:00:00+00:00",
        "observation_mode": "same_session_post_close",
        "prospective_eligible": eligible,
        "common_open_eligible": eligible,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "data_version": f"v-{date}",
        "byd": {
            "observation_sha256": f"byd-{date}",
            "data_version": f"byd-v-{date}",
            "observation_mode": "same_session_post_close",
            "prospective_eligible": eligible,
            "open_research_eligible": eligible,
            "base_target_position": target,
            "primary_raw_ohlcv": {"open": 100.0},
            "chain_linked_adjusted_ohlcv": {"open": 100.0},
            "company_actions": {"dividend": 0.0, "stock_split": 0.0},
            "market_state": "bear",
            "vol_state": "high",
        },
        "etf": {
            "chain_linked_adjusted_ohlcv": {"open": 10.0},
            "company_actions": {"dividend": 0.0, "stock_split": 0.0},
        },
        "targets": {
            "byd_v1_cash": {
                "byd_weight": target,
                "etf_weight": 0.0,
                "cash_weight": 1.0 - target,
            },
            "v1_dividend_75_25": {
                "byd_weight": target,
                "etf_weight": etf_weight,
                "cash_weight": 0.0,
            },
            "fixed_75_25": {
                "byd_weight": 0.75,
                "etf_weight": 0.25,
                "cash_weight": 0.0,
            },
        },
    }


def test_first_interval_starts_in_cash_and_uses_prior_close_signal() -> None:
    records = [
        _paired("2026-08-04", 0.75),
        _paired("2026-08-05", 1.0),
        _paired("2026-08-06", 1.0),
    ]
    frame = _observation_frame(records)
    executed = execute_next_common_open(frame, "v1_dividend_75_25")
    assert executed.iloc[0].to_dict() == {
        "position_byd_weight": 0.0,
        "position_etf_weight": 0.0,
        "position_cash_weight": 1.0,
    }
    assert executed.iloc[1]["position_byd_weight"] == 0.75
    assert executed.iloc[1]["position_etf_weight"] == 0.25
    assert executed.iloc[2]["position_byd_weight"] == 1.0


def test_ineligible_open_does_not_advance_position() -> None:
    records = [
        _paired("2026-08-04", 0.75),
        _paired("2026-08-05", 1.0, eligible=False),
        _paired("2026-08-06", 1.0),
    ]
    frame = _observation_frame(records)
    executed = execute_next_common_open(frame, "v1_dividend_75_25")
    assert executed.iloc[1].to_dict() == executed.iloc[0].to_dict()
    assert executed.iloc[2]["position_byd_weight"] == 1.0


def test_two_leg_rotation_costs_both_assets_and_cash() -> None:
    records = [
        _paired("2026-08-04", 0.75),
        _paired("2026-08-05", 1.0),
        _paired("2026-08-06", 1.0),
        _paired("2026-08-07", 1.0),
    ]
    records[1]["byd"]["chain_linked_adjusted_ohlcv"]["open"] = 101.0
    records[1]["etf"]["chain_linked_adjusted_ohlcv"]["open"] = 10.1
    records[2]["byd"]["chain_linked_adjusted_ohlcv"]["open"] = 102.0
    records[2]["etf"]["chain_linked_adjusted_ohlcv"]["open"] = 10.2
    records[3]["byd"]["chain_linked_adjusted_ohlcv"]["open"] = 103.0
    records[3]["etf"]["chain_linked_adjusted_ohlcv"]["open"] = 10.3
    frame = _observation_frame(records)
    daily = strategy_daily(
        frame,
        "v1_dividend_75_25",
        cost_bps=20.0,
    )
    assert np.isclose(daily.iloc[1]["turnover_units"], 2.0)
    assert np.isclose(daily.iloc[1]["cost"], 0.004)
    assert np.isclose(daily.iloc[2]["turnover_units"], 0.5)
    assert np.isclose(daily.iloc[2]["cost"], 0.001)


def test_append_only_store_is_idempotent_and_rejects_drift(
    tmp_path,
) -> None:
    observation = _paired("2026-08-04", 0.75)
    first = persist_store(tmp_path, [observation])
    second = persist_store(tmp_path, [observation])
    assert first["ledger_sha256"] == second["ledger_sha256"]
    changed = json.loads(json.dumps(observation))
    changed["targets"]["v1_dividend_75_25"]["etf_weight"] = 0.20
    with pytest.raises(RuntimeError, match="append-only record drift"):
        persist_store(tmp_path, [changed])


def test_pairing_references_sealed_byd_observation() -> None:
    date = pd.Timestamp("2026-08-04")
    extension = ChainLinkedExtension(
        adjusted_new=pd.DataFrame(
            [
                {
                    "date": date,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000.0,
                }
            ]
        ),
        primary_raw_new=pd.DataFrame(
            [
                {
                    "date": date,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000.0,
                }
            ]
        ),
        provider_payload_sha256="provider-sha",
        chain_scale=1.0,
        anchor_provider_adjusted_close=9.8,
        anchor_canonical_adjusted_close=9.8,
    )
    audit = IndependentAudit(
        row_audit=pd.DataFrame(
            [
                {
                    "date": date,
                    "open_research_eligible": True,
                    "independent_raw_confirmed": True,
                    "open_level_abs_pct_difference": 0.0,
                    "close_level_abs_pct_difference": 0.0,
                }
            ]
        ),
        secondary_payload_sha256="secondary-sha",
        secondary_provider="secondary",
    )
    byd = {
        "signal_date": "2026-08-04",
        "observation_sha256": "sealed-byd-sha",
        "data_version": "byd-v",
        "observation_mode": "same_session_post_close",
        "prospective_eligible": True,
        "open_research_eligible": True,
        "base_target_position": 0.75,
        "primary_raw_ohlcv": {"open": 100.0},
        "chain_linked_adjusted_ohlcv": {"open": 100.0},
        "company_actions": {"dividend": 0.0, "stock_split": 0.0},
        "factors": {"market_state": "bear", "vol_state": "high"},
    }
    provider = pd.DataFrame(
        [
            {
                "date": date,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000.0,
                "adj_close": 10.1,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
    )
    rows = build_paired_observations(
        byd_observations=[byd],
        extension=extension,
        audit=audit,
        provider_history=provider,
        existing_dates=set(),
        observed_at_utc="2026-08-04T10:00:00+00:00",
        primary_provider="primary",
        provider_parameters={},
        secondary_attempts=[],
        extended_adjusted_sha256="extended-sha",
    )
    assert len(rows) == 1
    assert rows[0]["byd"]["observation_sha256"] == "sealed-byd-sha"
    assert rows[0]["targets"]["v1_dividend_75_25"] == {
        "byd_weight": 0.75,
        "etf_weight": 0.25,
        "cash_weight": 0.0,
    }


def test_quarantined_pairing_serializes_missing_audit_values() -> None:
    date = pd.Timestamp("2026-08-04")
    market_row = {
        "date": date,
        "open": 10.0,
        "high": 10.2,
        "low": 9.9,
        "close": 10.1,
        "volume": 1000.0,
    }
    extension = ChainLinkedExtension(
        adjusted_new=pd.DataFrame([market_row]),
        primary_raw_new=pd.DataFrame([market_row]),
        provider_payload_sha256="provider-sha",
        chain_scale=1.0,
        anchor_provider_adjusted_close=9.8,
        anchor_canonical_adjusted_close=9.8,
    )
    audit = IndependentAudit(
        row_audit=pd.DataFrame(
            [
                {
                    "date": date,
                    "open_research_eligible": False,
                    "independent_raw_confirmed": False,
                    "open_level_abs_pct_difference": float("nan"),
                    "close_level_abs_pct_difference": float("nan"),
                }
            ]
        ),
        secondary_payload_sha256="secondary-sha",
        secondary_provider="secondary",
    )
    byd = {
        "signal_date": "2026-08-04",
        "observation_sha256": "sealed-byd-sha",
        "data_version": "byd-v",
        "observation_mode": "same_session_post_close",
        "prospective_eligible": True,
        "open_research_eligible": True,
        "base_target_position": 0.75,
        "primary_raw_ohlcv": {"open": 100.0},
        "chain_linked_adjusted_ohlcv": {"open": 100.0},
        "company_actions": {"dividend": 0.0, "stock_split": 0.0},
        "factors": {"market_state": "bear", "vol_state": "high"},
    }
    provider_row = {
        **market_row,
        "adj_close": 10.1,
        "dividends": float("nan"),
        "stock_splits": float("nan"),
    }

    rows = build_paired_observations(
        byd_observations=[byd],
        extension=extension,
        audit=audit,
        provider_history=pd.DataFrame([provider_row]),
        existing_dates=set(),
        observed_at_utc="2026-08-04T10:00:00+00:00",
        primary_provider="primary",
        provider_parameters={},
        secondary_attempts=[],
        extended_adjusted_sha256="extended-sha",
    )

    assert len(rows) == 1
    _json_bytes(rows[0])
    assert rows[0]["status"] == "prospective_paired_open_quarantined"
    assert rows[0]["etf"]["company_actions"] == {
        "dividend": 0.0,
        "stock_split": 0.0,
    }
    assert rows[0]["etf"]["independent_audit"] == {
        "confirmed": False,
        "open_level_abs_pct_difference": None,
        "close_level_abs_pct_difference": None,
    }
