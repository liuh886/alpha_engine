from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import scripts.ranker_provisional_mtm as mtm
from scripts.run_formal_refresh_transaction import (
    _has_current_provisional_mtm,
    _latest_settled_performance_end,
)
from src.governance.strategy_runtime_capabilities import (
    RANKER_FORMAL_REFRESH_ADAPTERS,
    load_active_strategy_runtime_capabilities,
)


def _write_close(provider: Path, instrument: str, values: list[float]) -> None:
    path = provider / "features" / instrument.lower() / "close.day.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray([0.0, *values], dtype="<f4").tofile(path)


def test_ranker_mtm_replaces_old_observation_and_advances_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_path = tmp_path / "ranker.json"
    package_path.write_text(
        json.dumps(
            {
                "model_id": "us_x1_3",
                "evidence_cutoff": "2026-08-05",
                "benchmark": "QQQ",
                "trace_frequency": "non_overlapping_10_session",
                "portfolio_contract": {"execution_delay_sessions": 0},
                "date_range": {"start": "2026-07-16", "end": "2026-08-05"},
                "freshness": {
                    "status": "current",
                    "required_cutoff": "2026-08-05",
                    "latest_completed_session": "2026-08-05",
                },
                "report": [
                    {
                        "date": "2026-07-16",
                        "holding_end_date": "2026-07-30",
                        "account": 2.0,
                        "bench_qqq": 1.2,
                    },
                    {
                        "date": "2026-08-05",
                        "signal_date": "2026-07-30",
                        "holding_end_date": "2026-08-05",
                        "account": 99.0,
                        "bench_qqq": 99.0,
                        "provisional_mtm": True,
                        "settlement_status": "provisional_mtm",
                    },
                ],
                "positions": [
                    {"date": "2026-07-30", "instrument": "OLD", "weight": 1.0}
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = tmp_path / "provider"
    sessions = [
        "2026-07-30",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    ]
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("\n".join(sessions) + "\n")
    _write_close(provider, "A", [100, 102, 104, 106, 108, 110])
    _write_close(provider, "B", [100, 98, 96, 94, 92, 90])
    _write_close(provider, "QQQ", [100, 101, 102, 103, 104, 105])
    monkeypatch.setattr(
        mtm,
        "read_latest_evaluation",
        lambda *_args, **_kwargs: {
            "signal": {
                "signal_date": "2026-07-30",
                "target_weights": {"A": 0.5, "B": 0.5},
                "estimated_transaction_cost": 0.001,
                "turnover_units": 0.5,
            }
        },
    )

    result = mtm.attach_ranker_provisional_mtm(
        package_path=package_path,
        provider_dir=provider,
        ledger_dir=tmp_path / "ledger",
        cutoff="2026-08-07",
    )

    assert result is not None
    persisted = json.loads(package_path.read_text(encoding="utf-8"))
    assert len(persisted["report"]) == 1
    assert persisted["report"][0]["account"] == 2.0
    assert persisted["evidence_cutoff"] == "2026-08-07"
    assert persisted["date_range"]["end"] == "2026-08-07"
    assert persisted["freshness"]["latest_completed_session"] == "2026-08-07"
    assert persisted["provisional_mtm"]["as_of"] == "2026-08-07"
    assert persisted["provisional_mtm"]["source"] == "strategy_signal_ledger"
    performance_row = persisted["provisional_mtm"]["performance_row"]
    assert performance_row["provisional_mtm"] is True
    assert performance_row["turnover"] == 0.0
    assert performance_row["rebalance_date"] == "2026-07-30"
    assert performance_row["rebalance_turnover"] == 0.5
    assert performance_row["account_before"] == 2.0


def test_ranker_mtm_fails_closed_when_due_signal_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_path = tmp_path / "ranker.json"
    package_path.write_text(
        json.dumps(
            {
                "model_id": "us_x1_3",
                "evidence_cutoff": "2026-07-30",
                "trace_frequency": "non_overlapping_10_session",
                "portfolio_contract": {"execution_delay_sessions": 0},
                "report": [
                    {
                        "date": "2026-07-02",
                        "holding_end_date": "2026-07-16",
                        "account": 1.0,
                        "bench_qqq": 1.0,
                    }
                ],
                "positions": [
                    {"date": "2026-07-16", "instrument": "OLD", "weight": 1.0}
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = tmp_path / "provider"
    sessions = [
        "2026-07-16",
        "2026-07-17",
        "2026-07-20",
        "2026-07-21",
        "2026-07-22",
        "2026-07-23",
        "2026-07-24",
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
    ]
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("\n".join(sessions) + "\n")
    monkeypatch.setattr(mtm, "read_latest_evaluation", lambda *_args, **_kwargs: None)

    with pytest.raises(
        mtm.RankerProvisionalMtmError,
        match="MTM cannot advance forward state",
    ):
        mtm.attach_ranker_provisional_mtm(
            package_path=package_path,
            provider_dir=provider,
            ledger_dir=tmp_path / "ledger",
            cutoff="2026-07-30",
        )


def test_ranker_mtm_rejects_formal_state_ahead_of_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mtm,
        "read_latest_evaluation",
        lambda *_args, **_kwargs: {
            "signal": {
                "signal_date": "2026-07-16",
                "target_weights": {"A": 1.0},
            }
        },
    )

    with pytest.raises(
        mtm.RankerProvisionalMtmError,
        match="formal ranker state is ahead",
    ):
        mtm._latest_governed_signal(
            model_id="us_x1_3",
            formal_signal_date="2026-07-30",
            cutoff="2026-08-07",
            ledger_dir=Path("unused"),
        )


def test_mtm_contract_targets_active_us_and_cn_rankers() -> None:
    capabilities = load_active_strategy_runtime_capabilities()
    maintained = {
        row.model_version_id
        for row in capabilities.values()
        if row.formal_refresh.adapter_id in RANKER_FORMAL_REFRESH_ADAPTERS
    }
    assert maintained == {"us_x1_3"}
    assert capabilities["cn_x"].formal_refresh.status == "blocked"
    performance = {
        "report": [
            {"date": "2026-07-29", "holding_end_date": "2026-07-29"}
        ]
    }
    assert _latest_settled_performance_end(performance) == "2026-07-29"
    assert _has_current_provisional_mtm(
        performance,
        cutoff="2026-08-07",
        signal_date="2026-07-29",
    ) is False


def test_mtm_contract_requires_matching_signal_identity() -> None:
    performance = {
        "report": [
            {"date": "2026-07-29", "holding_end_date": "2026-07-29"},
            {
                "date": "2026-08-07",
                "signal_date": "2026-07-29",
                "holding_end_date": "2026-08-07",
                "provisional_mtm": True,
                "settlement_status": "provisional_mtm",
            },
        ]
    }
    assert _latest_settled_performance_end(performance) == "2026-07-29"
    assert _has_current_provisional_mtm(
        performance,
        cutoff="2026-08-07",
        signal_date="2026-07-29",
    ) is True
    assert _has_current_provisional_mtm(
        performance,
        cutoff="2026-08-07",
        signal_date="2026-08-05",
    ) is False
