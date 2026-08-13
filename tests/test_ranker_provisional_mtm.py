from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import scripts.ranker_provisional_mtm as mtm
from scripts.run_formal_refresh_transaction import (
    RANKER_MTM_MODELS,
    _has_current_provisional_mtm,
    _latest_settled_performance_end,
)


def _write_close(provider: Path, instrument: str, values: list[float]) -> None:
    path = provider / "features" / instrument.lower() / "close.day.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray([0.0, *values], dtype="<f4").tofile(path)


def test_ranker_mtm_keeps_settled_trace_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_path = tmp_path / "ranker.json"
    package_path.write_text(
        json.dumps(
            {
                "model_id": "us_x1_1",
                "evidence_cutoff": "2026-08-07",
                "benchmark": "QQQ",
                "trace_frequency": "non_overlapping_10_session",
                "portfolio_contract": {"execution_delay_sessions": 0},
                "freshness": {"status": "current"},
                "report": [
                    {
                        "date": "2026-07-16",
                        "holding_end_date": "2026-07-30",
                        "account": 2.0,
                        "bench_qqq": 1.2,
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
        repository_root=tmp_path,
    )

    assert result is not None
    persisted = json.loads(package_path.read_text(encoding="utf-8"))
    assert len(persisted["report"]) == 1
    assert persisted["provisional_mtm"]["as_of"] == "2026-08-07"
    assert persisted["provisional_mtm"]["performance_row"]["provisional_mtm"] is True


def test_mtm_contract_targets_only_cn_x1_1_and_detects_stale_settled_trace() -> None:
    assert RANKER_MTM_MODELS == (("cn_x1_1", "cn"),)
    performance = {
        "report": [
            {"date": "2026-07-29", "holding_end_date": "2026-07-29"}
        ]
    }
    assert _latest_settled_performance_end(performance) == "2026-07-29"
    assert _has_current_provisional_mtm(performance, cutoff="2026-08-07") is False


def test_mtm_contract_accepts_current_bundle_v2_projection() -> None:
    performance = {
        "report": [
            {"date": "2026-07-29", "holding_end_date": "2026-07-29"},
            {
                "date": "2026-08-07",
                "holding_end_date": "2026-08-07",
                "provisional_mtm": True,
                "settlement_status": "provisional_mtm",
            },
        ]
    }
    assert _latest_settled_performance_end(performance) == "2026-07-29"
    assert _has_current_provisional_mtm(performance, cutoff="2026-08-07") is True
