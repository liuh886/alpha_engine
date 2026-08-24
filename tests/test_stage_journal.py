"""Stage journals must resume deterministically and fail closed on drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.stage_journal import (
    StageJournal,
    fingerprint,
    canonical_bytes,
)


def _payload(seed: int = 1) -> dict:
    return {
        "market": "cn",
        "window": {"label": f"2024H{seed}", "train_start": "2024-01-02"},
        "symbols": ["000001", "600519"],
    }


def test_fingerprint_is_canonical_and_key_order_free() -> None:
    assert fingerprint({"a": 1, "b": [1, 2]}) == fingerprint({"b": [1, 2], "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})


def test_record_then_decide_reuses_matching_fingerprint(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    fp = fingerprint(_payload())
    result = {"report_rows": 57, "supported": False}

    assert journal.decide(stage_id="window_2024H1", fp=fp).action == "run"

    journal.record(stage_id="window_2024H1", fp=fp, result=result)
    decision = journal.decide(stage_id="window_2024H1", fp=fp)
    assert decision.action == "reuse"
    assert decision.result == result


def test_changed_inputs_rerun_instead_of_reusing(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    journal.record(
        stage_id="window_2024H1",
        fp=fingerprint(_payload(seed=1)),
        result={"report_rows": 57},
    )

    decision = journal.decide(
        stage_id="window_2024H1", fp=fingerprint(_payload(seed=2))
    )
    assert decision.action == "run"
    assert decision.result is None


def test_missing_required_artifact_forces_rerun(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    fp = fingerprint(_payload())
    artifact = tmp_path / "windows" / "report.json"
    journal.record(stage_id="w", fp=fp, result={"rows": 10})

    decision = journal.decide(stage_id="w", fp=fp, required_artifacts=(artifact,))
    assert decision.action == "run"

    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    assert journal.decide(stage_id="w", fp=fp, required_artifacts=(artifact,)).action == "reuse"


def test_corrupt_entry_fails_closed(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    stage_dir = tmp_path / "stage_journal"
    stage_dir.mkdir(parents=True)
    (stage_dir / "broken.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt stage journal"):
        journal.decide(stage_id="broken", fp=fingerprint(_payload()))


def test_atomic_write_leaves_no_tmp_residue(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    journal.record(stage_id="w", fp="f" * 64, result={})
    entries = list((tmp_path / "stage_journal").glob("*.tmp"))
    assert entries == []
    payload = json.loads(
        (tmp_path / "stage_journal" / "w.json").read_text(encoding="utf-8")
    )
    assert payload["fingerprint"] == "f" * 64


def test_unsafe_stage_id_is_rejected(tmp_path: Path) -> None:
    journal = StageJournal(tmp_path)
    with pytest.raises(ValueError, match="unsafe stage_id"):
        journal.record(stage_id="../escape", fp="f" * 64, result={})


def test_canonical_bytes_reject_non_finite_floats() -> None:
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})


def test_roundtrip_preserves_observation_row_fidelity(tmp_path: Path) -> None:
    """Observation rows recorded for resume must survive byte-exactly."""

    rows = [
        {
            "candidate_id": "alpha158_baseline",
            "window": "2024H1",
            "cost_bps": 20,
            "relative_excess": 0.04798990466643405,
            "strategy_return": 0.113254261403144,
            "benchmark_return": 0.06526435673670995,
            "max_drawdown": -0.127254261403144,
            "rank_ic": 0.031,
            "icir": 0.62,
        },
        {
            "candidate_id": "alpha158_challenger",
            "window": "2024H1",
            "cost_bps": 60,
            "relative_excess": -0.002,
            "strategy_return": 0.0,
            "benchmark_return": 0.002,
            "max_drawdown": -0.05,
            "rank_ic": -0.01,
            "icir": -0.1,
        },
    ]
    journal = StageJournal(tmp_path)
    fp = fingerprint({"stage": "window_2024H1"})
    journal.record(stage_id="window_2024H1", fp=fp, result={"observations": rows})

    reused = journal.decide(stage_id="window_2024H1", fp=fp)
    assert reused.action == "reuse"
    assert reused.result is not None
    assert reused.result["observations"] == rows
