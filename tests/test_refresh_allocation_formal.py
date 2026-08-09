from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_allocation_formal import (
    AllocationRefreshError,
    _extend_byd_input,
    _extend_etf_input,
    _increment_qqq_attribution,
    _qqq_metrics_from_report,
    _verify_qqq_decision_overlap,
)


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "position_state": [1, 1],
            "decision_state": [1, 2],
            "position_label": ["attack", "attack"],
            "decision_reason": ["hold", "enter_leverage"],
            "executed_reason": ["enter_attack", "hold"],
            "weight_QQQI": [0.5, 0.5],
            "weight_QQQ": [0.5, 0.5],
            "weight_TQQQ": [0.0, 0.0],
            "QQQI_next_open_return": [0.01, 0.02],
            "QQQ_next_open_return": [0.02, 0.01],
            "TQQQ_next_open_return": [0.03, 0.02],
            "transaction_cost": [0.0, 0.001],
        },
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_byd_extension_normalizes_prospective_date_dtype(tmp_path: Path) -> None:
    base = tmp_path / "byd-base"
    shadow = tmp_path / "byd-shadow"
    output = tmp_path / "byd-output"
    base.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-08-03",
                "open": 90.0,
                "high": 91.0,
                "low": 89.0,
                "close": 90.5,
                "volume": 1000.0,
            }
        ]
    ).to_csv(base / "adjusted_ohlcv.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-08-03", "open_research_eligible": True}]
    ).to_csv(base / "session_audit.csv", index=False)
    _write_json(base / "manifest.json", {"cutoff": "2026-08-03"})
    _write_json(shadow / "manifest.json", {"last_signal_date": "2026-08-04"})
    _write_json(
        shadow / "observations" / "2026-08-04.json",
        {
            "signal_date": "2026-08-04",
            "open_research_eligible": True,
            "chain_linked_adjusted_ohlcv": {
                "open": 91.0,
                "high": 92.0,
                "low": 90.0,
                "close": 91.5,
                "volume": 1100.0,
            },
        },
    )

    manifest = _extend_byd_input(
        base_dir=base,
        shadow_store=shadow,
        cutoff="2026-08-04",
        output_dir=output,
    )

    adjusted = pd.read_csv(output / "adjusted_ohlcv.csv")
    sessions = pd.read_csv(output / "session_audit.csv")
    assert adjusted["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert sessions["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert manifest["cutoff"] == "2026-08-04"


def test_etf_extension_normalizes_all_prospective_date_dtypes(tmp_path: Path) -> None:
    base = tmp_path / "etf-base"
    paired = tmp_path / "paired"
    output = tmp_path / "etf-output"
    base.mkdir()
    base_row = {
        "date": "2026-08-03",
        "open": 1.40,
        "high": 1.42,
        "low": 1.39,
        "close": 1.41,
        "volume": 1000.0,
    }
    pd.DataFrame([base_row]).to_csv(base / "raw_ohlcv.csv", index=False)
    pd.DataFrame(
        [
            {
                **base_row,
                "factor": 1.0,
                "adjustment_anchor_date": "2026-08-03",
                "adjustment_anchor_factor": 1.0,
                "price_role": "adjusted_feature_and_label",
            }
        ]
    ).to_csv(base / "adjusted_ohlcv.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-08-03", "open_research_eligible": True}]
    ).to_csv(base / "session_audit.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-08-03", "dividend": 0.0, "stock_split": 0.0}]
    ).to_csv(base / "corporate_actions.csv", index=False)
    _write_json(base / "manifest.json", {"cutoff": "2026-08-03"})
    _write_json(paired / "manifest.json", {"last_signal_date": "2026-08-04"})
    _write_json(
        paired / "observations" / "2026-08-04.json",
        {
            "signal_date": "2026-08-04",
            "etf": {
                "open_research_eligible": True,
                "primary_raw_ohlcv": {
                    "open": 1.41,
                    "high": 1.43,
                    "low": 1.40,
                    "close": 1.42,
                    "volume": 1200.0,
                },
                "chain_linked_adjusted_ohlcv": {
                    "open": 1.41,
                    "high": 1.43,
                    "low": 1.40,
                    "close": 1.42,
                    "volume": 1200.0,
                },
                "company_actions": {"dividend": 0.01, "stock_split": 0.0},
            },
        },
    )

    manifest = _extend_etf_input(
        base_dir=base,
        paired_store=paired,
        cutoff="2026-08-04",
        output_dir=output,
    )

    for filename in (
        "raw_ohlcv.csv",
        "adjusted_ohlcv.csv",
        "session_audit.csv",
        "corporate_actions.csv",
    ):
        frame = pd.read_csv(output / filename)
        assert frame["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert manifest["cutoff"] == "2026-08-04"


def test_overlap_ignores_revised_economic_return_but_locks_decision_path() -> None:
    existing = {
        "2026-07-30": {
            "period_return": -0.99,
            "gross_return": -0.99,
            "transaction_cost": 0.25,
            "position_state": 1,
            "decision_state": 1,
            "position_label": "attack",
            "decision_reason": "hold",
            "executed_reason": "enter_attack",
            "weight_QQQI": 0.5,
            "weight_QQQ": 0.5,
            "weight_TQQQ": 0.0,
        }
    }
    _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_fails_closed_when_frozen_decision_path_changes() -> None:
    existing = {
        "2026-07-30": {
            "position_state": 0,
            "decision_state": 1,
            "weight_QQQI": 1.0,
            "weight_QQQ": 0.0,
            "weight_TQQQ": 0.0,
        }
    }
    with pytest.raises(AllocationRefreshError, match="decision path changed"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_requires_all_frozen_decision_dates_to_be_replayed() -> None:
    existing = {
        "2026-07-29": {"position_state": 1, "decision_state": 1},
    }
    with pytest.raises(AllocationRefreshError, match="missing 1 frozen decision dates"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_metrics_are_recomputed_from_frozen_plus_appended_report() -> None:
    report = [
        {
            "date": "2026-07-29",
            "period_return": 0.01,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
        {
            "date": "2026-07-30",
            "period_return": -0.005,
            "turnover": 1.0,
            "transaction_cost": 0.001,
        },
        {
            "date": "2026-07-31",
            "period_return": 0.02,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
    ]
    metrics = _qqq_metrics_from_report(report, annual_risk_free_rate=0.0)
    assert metrics["Total Return"] == pytest.approx((1.01 * 0.995 * 1.02) - 1.0)
    assert metrics["Turnover"] == pytest.approx(1.0)
    assert metrics["Transaction Cost"] == pytest.approx(0.001)


def test_attribution_extends_only_new_sessions_from_frozen_values() -> None:
    existing = [
        {"instrument": "QQQI", "value": 0.10},
        {"instrument": "QQQ", "value": 0.20},
        {"instrument": "TQQQ", "value": 0.30},
    ]
    result = _increment_qqq_attribution(
        existing=existing,
        daily=_daily(),
        appended_dates={"2026-07-31"},
        previous_weights={"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
    )
    values = {row["instrument"]: row["value"] for row in result}
    assert values["QQQI"] == pytest.approx(0.11)
    assert values["QQQ"] == pytest.approx(0.205)
    assert values["TQQQ"] == pytest.approx(0.30)
