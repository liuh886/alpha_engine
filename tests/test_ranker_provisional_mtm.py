from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import scripts.ranker_provisional_mtm as mtm
from scripts.run_formal_refresh_transaction import _mtm_refresh_model_ids


def _write_close(provider: Path, instrument: str, values: list[float]) -> None:
    path = provider / "features" / instrument.lower() / "close.day.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray([0.0, *values], dtype="<f4").tofile(path)


def _write_ranker_package(
    root: Path,
    *,
    model_id: str,
    settled_end: str,
    cutoff: str,
    provisional_as_of: str | None = None,
) -> None:
    benchmark_key = "bench_qqq" if model_id == "us_x1_1" else "bench_hs300"
    payload: dict[str, object] = {
        "model_id": model_id,
        "evidence_cutoff": cutoff,
        "freshness": {
            "status": "current",
            "latest_realized_holding_end": settled_end,
        },
        "report": [
            {
                "date": settled_end,
                "holding_end_date": settled_end,
                "account": 1.0,
                benchmark_key: 1.0,
            }
        ],
    }
    if provisional_as_of is not None:
        payload["provisional_mtm"] = {
            "schema_version": "ranker_provisional_mtm_v1",
            "as_of": provisional_as_of,
            "research_only": True,
            "trade_ready": False,
            "performance_row": {
                "date": settled_end,
                "holding_end_date": provisional_as_of,
                "provisional_mtm": True,
                "settlement_status": "provisional_mtm",
            },
        }
    (root / f"{model_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_ranker_mtm_marks_current_target_to_evidence_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_path = tmp_path / "us_x1_1.json"
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
                        "window": "2026H2_partial",
                        "evaluation": "reporting",
                    }
                ],
                "positions": [
                    {"date": "2026-07-16", "instrument": "OLD", "weight": 1.0},
                    {"date": "2026-07-30", "instrument": "CURRENT", "weight": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    provider = tmp_path / "provider"
    calendar = [
        "2026-07-30",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    ]
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("\n".join(calendar) + "\n")
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
    assert result["signal_date"] == "2026-07-30"
    row = result["performance_row"]
    assert row["holding_end_date"] == "2026-08-07"
    assert row["provisional_mtm"] is True
    assert row["settlement_status"] == "provisional_mtm"
    assert row["gross_return"] == pytest.approx(0.0)
    assert row["period_return"] == pytest.approx(-0.001)
    assert row["account"] == pytest.approx(1.998)
    assert row["benchmark_return"] == pytest.approx(0.05)
    assert row["bench_qqq"] == pytest.approx(1.26)

    persisted = json.loads(package_path.read_text(encoding="utf-8"))
    assert len(persisted["report"]) == 1
    assert persisted["report"][0]["date"] == "2026-07-16"
    assert persisted["provisional_mtm"]["as_of"] == "2026-08-07"
    assert persisted["freshness"]["latest_mtm_date"] == "2026-08-07"
    assert persisted["freshness"]["performance_observation_status"] == "provisional_mtm"


def test_mtm_planner_refreshes_current_cutoff_when_performance_is_stale(
    tmp_path: Path,
) -> None:
    _write_ranker_package(
        tmp_path,
        model_id="us_x1_1",
        settled_end="2026-07-30",
        cutoff="2026-08-07",
    )
    _write_ranker_package(
        tmp_path,
        model_id="cn_x1_1",
        settled_end="2026-07-29",
        cutoff="2026-08-07",
    )

    assert _mtm_refresh_model_ids(
        tmp_path,
        cutoffs={"us": "2026-08-07", "cn": "2026-08-07"},
    ) == ("us_x1_1", "cn_x1_1")


def test_mtm_planner_is_current_after_cutoff_mtm_is_published(tmp_path: Path) -> None:
    for model_id, settled_end in (
        ("us_x1_1", "2026-07-30"),
        ("cn_x1_1", "2026-07-29"),
    ):
        _write_ranker_package(
            tmp_path,
            model_id=model_id,
            settled_end=settled_end,
            cutoff="2026-08-07",
            provisional_as_of="2026-08-07",
        )

    assert _mtm_refresh_model_ids(
        tmp_path,
        cutoffs={"us": "2026-08-07", "cn": "2026-08-07"},
    ) == ()
