from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

import src.research.byd_v1_2_trend_expansion_prospective as prospective


def _source_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    byd: list[dict[str, object]] = []
    paired: list[dict[str, object]] = []
    for index, date in enumerate(("2026-08-06", "2026-08-07", "2026-08-08")):
        byd.append(
            {
                "signal_date": date,
                "source_sha256": f"{index + 1:064x}",
                "data_version": f"byd-{date}",
                "base_target_position": 1.0,
            }
        )
        paired.append(
            {
                "signal_date": date,
                "source_sha256": f"{index + 11:064x}",
                "data_version": f"paired-{date}",
                "observed_at_utc": f"{date}T08:00:00+00:00",
                "common_open_eligible": True,
                "prospective_eligible": True,
                "byd": {
                    "chain_linked_adjusted_ohlcv": {
                        "open": 100.0 + index,
                    }
                },
                "etf": {
                    "chain_linked_adjusted_ohlcv": {
                        "open": 1.5 + index * 0.01,
                    }
                },
            }
        )
    return byd, paired


def _dataset() -> pd.DataFrame:
    index = pd.to_datetime(["2026-08-06", "2026-08-07", "2026-08-08"])
    return pd.DataFrame(
        {
            "market_state": ["bull", "bull", "sideways"],
            "vol_state": ["low", "low", "low"],
            "mom_20": [0.10, 0.08, 0.05],
            "mom_60": [0.20, 0.18, 0.15],
            "drawdown_252": [-0.03, -0.04, -0.05],
        },
        index=index,
    )


def test_observations_rebuild_state_from_origin_and_reproduce_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    byd, paired = _source_rows()
    dataset = _dataset()

    def fake_sources(path: str | Path) -> list[dict[str, object]]:
        rows = byd if str(path) == "byd" else paired
        return copy.deepcopy(rows)

    monkeypatch.setattr(prospective, "source_records", fake_sources)
    monkeypatch.setattr(
        prospective,
        "rebuild_byd_dataset",
        lambda _baseline, _records: dataset.copy(),
    )
    monkeypatch.setattr(
        prospective,
        "build_v1_0_decision_position",
        lambda _dataset: pd.Series(1.0, index=dataset.index),
    )

    records = prospective.build_observations(
        baseline_dir="baseline",
        byd_store="byd",
        paired_store="paired",
        existing_records=[],
    )

    assert [row["trend_expansion_active"] for row in records] == [
        True,
        True,
        False,
    ]
    assert records[0]["targets"]["byd_v1_2_trend_expansion_1125"] == {
        "byd_weight": 1.125,
        "etf_weight": 0.0,
        "cash_weight": -0.125,
    }
    assert records[-1]["targets"]["byd_v1_2_trend_expansion_1125"] == {
        "byd_weight": 1.0,
        "etf_weight": 0.0,
        "cash_weight": 0.0,
    }

    repeated = prospective.build_observations(
        baseline_dir="baseline",
        byd_store="byd",
        paired_store="paired",
        existing_records=copy.deepcopy(records),
    )
    assert repeated == []


def _trend_record(date: str, *, active: bool, byd_open: float) -> dict[str, object]:
    baseline = {"byd_weight": 1.0, "etf_weight": 0.0, "cash_weight": 0.0}
    candidate = (
        {"byd_weight": 1.125, "etf_weight": 0.0, "cash_weight": -0.125}
        if active
        else dict(baseline)
    )
    return {
        "schema_version": prospective.SCHEMA_VERSION,
        "kind": "trend_expansion_observation",
        "signal_date": date,
        "observed_at_utc": f"{date}T08:00:00+00:00",
        "source": {},
        "common_open_eligible": True,
        "prospective_eligible": True,
        "entry_condition": active,
        "exit_condition": not active,
        "trend_expansion_active": active,
        "factors": {
            "base_target_position": 1.0,
            "market_state": "bull" if active else "sideways",
            "vol_state": "low",
            "mom_20": 0.1,
            "mom_60": 0.2,
            "drawdown_252": -0.03,
        },
        "prices": {"byd_open": byd_open, "etf_open": 1.5},
        "targets": {
            "byd_v1_1": baseline,
            "byd_v1_2_trend_expansion_1125": candidate,
        },
        "cost_contract": prospective.SCENARIOS,
        "status": "prospective_trend_expansion_active" if active else "prospective_observation",
        "data_version": f"trend-{date}",
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
    }


def test_next_common_open_financing_is_charged_after_signal() -> None:
    records = [
        _trend_record("2026-08-06", active=True, byd_open=100.0),
        _trend_record("2026-08-07", active=True, byd_open=102.0),
        _trend_record("2026-08-10", active=False, byd_open=103.0),
    ]
    frame = prospective._frame(records)
    daily = prospective.strategy_daily(
        frame,
        "byd_v1_2_trend_expansion_1125",
        cost_bps=20.0,
        annual_financing_rate=0.06,
    )

    assert daily.iloc[0]["borrowed_weight"] == pytest.approx(0.0)
    assert daily.iloc[1]["borrowed_weight"] == pytest.approx(0.125)
    assert daily.iloc[1]["financing_cost"] == pytest.approx(
        0.125 * 0.06 / 252.0
    )
    assert daily.iloc[1]["net_return"] < daily.iloc[1]["gross_return"]


def test_single_observation_scorecard_waits_without_fabricating_returns() -> None:
    record = _trend_record("2026-08-06", active=True, byd_open=100.0)
    scorecard = prospective.build_scorecard([record], [])

    assert scorecard["status"] == "awaiting_return_interval"
    assert scorecard["observation_count"] == 1
    assert scorecard["scenarios"] == {}
    assert scorecard["all_gates_passed"] is False
    assert not any(scorecard["gates"].values())


def test_persist_store_is_append_only(tmp_path: Path) -> None:
    record = _trend_record("2026-08-06", active=True, byd_open=100.0)
    first = prospective.persist_store(tmp_path, [copy.deepcopy(record)])
    second = prospective.persist_store(tmp_path, [copy.deepcopy(record)])

    assert first == second
    changed = copy.deepcopy(record)
    changed["prices"]["byd_open"] = 101.0
    with pytest.raises(RuntimeError, match="append-only record drift"):
        prospective.persist_store(tmp_path, [changed])
