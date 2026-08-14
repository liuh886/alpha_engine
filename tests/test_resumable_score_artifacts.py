"""Focused recovery tests for governed long-running score materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.cn_ranker_exact_portfolio_replay import _score_hash
from src.research.resumable_score_artifacts import RunStateTracker, ScoreCheckpointStore


def _scores() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-05"), "000001"),
            (pd.Timestamp("2026-01-05"), "000002"),
        ],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"score": [0.125, -0.25]}, index=index)
    frame.attrs["provenance"] = "test"
    return frame


def _contract() -> dict:
    return {
        "schema_version": "1.0",
        "provider_identity_sha256": "a" * 64,
        "factor_contract": {"expressions": ["Ref($close, 1)"]},
        "window": {"label": "2026H1", "train_end": "2025-12-31"},
    }


def test_checkpoint_is_atomic_and_reused_only_explicitly(tmp_path: Path) -> None:
    store = ScoreCheckpointStore(tmp_path / "scores")
    fits = 0

    def fit() -> pd.DataFrame:
        nonlocal fits
        fits += 1
        return _scores()

    first, first_receipt = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="primary",
        resume=False,
        fit=fit,
        score_hash=_score_hash,
    )
    checkpoint = Path(first_receipt["path"])
    assert fits == 1
    assert first_receipt["reused"] is False
    assert (checkpoint / "scores.csv").is_file()
    assert (checkpoint / "manifest.json").is_file()
    assert not list(checkpoint.glob("*.tmp"))

    with pytest.raises(ValueError, match="explicit resume"):
        store.load_or_fit(
            contract=_contract(),
            window="2026H1",
            pass_id="primary",
            resume=False,
            fit=fit,
            score_hash=_score_hash,
        )

    resumed, resumed_receipt = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="primary",
        resume=True,
        fit=fit,
        score_hash=_score_hash,
    )
    assert fits == 1
    assert resumed_receipt["reused"] is True
    pd.testing.assert_frame_equal(first, resumed)
    assert first.attrs == resumed.attrs


def test_checkpoint_identity_tampering_fails_closed(tmp_path: Path) -> None:
    store = ScoreCheckpointStore(tmp_path / "scores")
    _, receipt = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="primary",
        resume=False,
        fit=_scores,
        score_hash=_score_hash,
    )
    manifest_path = Path(receipt["path"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract"]["provider_identity_sha256"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="identity mismatch"):
        store.load_or_fit(
            contract=_contract(),
            window="2026H1",
            pass_id="primary",
            resume=True,
            fit=_scores,
            score_hash=_score_hash,
        )


def test_checkpoint_content_corruption_fails_closed(tmp_path: Path) -> None:
    store = ScoreCheckpointStore(tmp_path / "scores")
    _, receipt = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="primary",
        resume=False,
        fit=_scores,
        score_hash=_score_hash,
    )
    data_path = Path(receipt["path"]) / "scores.csv"
    data_path.write_text(data_path.read_text(encoding="utf-8") + "corrupt\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content hash mismatch"):
        store.load_or_fit(
            contract=_contract(),
            window="2026H1",
            pass_id="primary",
            resume=True,
            fit=_scores,
            score_hash=_score_hash,
        )


def test_primary_and_reproduction_passes_are_distinct(tmp_path: Path) -> None:
    store = ScoreCheckpointStore(tmp_path / "scores")
    _, primary = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="primary",
        resume=False,
        fit=_scores,
        score_hash=_score_hash,
    )
    _, reproduction = store.load_or_fit(
        contract=_contract(),
        window="2026H1",
        pass_id="reproduction",
        resume=False,
        fit=_scores,
        score_hash=_score_hash,
    )
    assert primary["path"] != reproduction["path"]
    assert primary["score_sha256"] == reproduction["score_sha256"]


def test_run_state_records_progress_and_terminal_failure(tmp_path: Path) -> None:
    tracker = RunStateTracker(
        tmp_path,
        experiment_id="cn_x1_2_test",
        runner="test_runner",
        spec_identity_sha256="c" * 64,
        total_fit_units=15,
        resume=False,
        heartbeat_seconds=0,
    )
    tracker.start()
    tracker.begin_unit(
        {
            "unit_key": "primary/candidate/2026H1",
            "candidate_id": "candidate",
            "window": "2026H1",
            "pass_id": "primary",
        }
    )
    tracker.complete_unit(
        "primary/candidate/2026H1",
        {"score_sha256": "d" * 64, "reused": False},
    )
    try:
        raise RuntimeError("deliberate failure")
    except RuntimeError as exc:
        tracker.fail(exc)

    state = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["exit_code"] == 1
    assert state["completed_fit_units"] == 1
    assert state["total_fit_units"] == 15
    assert state["checkpoint_hashes"]["primary/candidate/2026H1"] == "d" * 64
    assert state["error"]["type"] == "RuntimeError"
    events = [
        json.loads(line)["event"]
        for line in (tmp_path / "run_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "run_started",
        "fit_unit_started",
        "fit_unit_completed",
        "run_failed",
    ]


def test_run_state_requires_explicit_matching_resume(tmp_path: Path) -> None:
    tracker = RunStateTracker(
        tmp_path,
        experiment_id="cn_x1_2_test",
        runner="test_runner",
        spec_identity_sha256="e" * 64,
        total_fit_units=15,
        resume=False,
        heartbeat_seconds=0,
    )
    tracker.start()
    tracker.finish(status="completed", decision="test")
    completed = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert completed["exit_code"] == 0

    with pytest.raises(ValueError, match="explicit resume"):
        RunStateTracker(
            tmp_path,
            experiment_id="cn_x1_2_test",
            runner="test_runner",
            spec_identity_sha256="e" * 64,
            total_fit_units=15,
            resume=False,
            heartbeat_seconds=0,
        )
    with pytest.raises(ValueError, match="spec identity mismatch"):
        RunStateTracker(
            tmp_path,
            experiment_id="cn_x1_2_test",
            runner="test_runner",
            spec_identity_sha256="f" * 64,
            total_fit_units=15,
            resume=True,
            heartbeat_seconds=0,
        )
