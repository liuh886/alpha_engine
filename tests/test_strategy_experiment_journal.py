from __future__ import annotations

import json

import pytest

from src.research.strategy_experiment_journal import (
    StrategyExperimentJournal,
    load_strategy_run_records,
    write_strategy_run_record,
)


def _record(experiment_id: str = "vix_v3", run_id: str = "run-001") -> dict:
    return {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "run_id": run_id,
        "created_at": "2026-08-01T00:00:00+00:00",
        "status": "completed",
        "market": "us",
        "strategy_family": "qqqi_qqq_tqqq_vix_rotation",
        "research_only": True,
        "trade_ready": False,
        "contract": {"path": "config.yaml", "sha256": "abc"},
        "metrics": {"cagr": 0.25, "max_drawdown": -0.22},
    }


def test_strategy_run_record_round_trip(tmp_path) -> None:
    path = write_strategy_run_record(_record(), root=tmp_path)
    assert path == tmp_path / "vix_v3" / "run-001" / "run_record.json"
    loaded = load_strategy_run_records(root=tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["metrics"]["cagr"] == 0.25


def test_journal_filters_and_latest(tmp_path) -> None:
    journal = StrategyExperimentJournal(tmp_path)
    journal.record(_record(run_id="run-001"))
    second = _record(run_id="run-002")
    second["created_at"] = "2026-08-02T00:00:00+00:00"
    journal.record(second)
    other = _record(experiment_id="other", run_id="run-003")
    other["market"] = "cn"
    journal.record(other)

    assert journal.latest("vix_v3")["run_id"] == "run-002"
    assert len(journal.list_runs(market="us")) == 2
    assert journal.summary(market="us")["total_experiments"] == 1
    assert journal.search("max_drawdown")[0]["experiment_id"] == "vix_v3"


def test_malformed_records_fail_closed(tmp_path) -> None:
    malformed = tmp_path / "bad" / "run" / "run_record.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text(json.dumps({"experiment_id": "bad"}), encoding="utf-8")
    assert load_strategy_run_records(root=tmp_path) == []


def test_record_rejects_unsafe_identity(tmp_path) -> None:
    record = _record(experiment_id="../escape")
    with pytest.raises(ValueError, match="experiment_id"):
        write_strategy_run_record(record, root=tmp_path)
