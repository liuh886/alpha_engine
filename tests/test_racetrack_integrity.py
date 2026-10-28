"""Regression tests for retained evidence and publication failure boundaries."""

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from src.racetrack import pipeline
from src.racetrack.contracts import (
    CalendarSessionError,
    EngineConfig,
    LedgerOverwriteError,
    LedgerTamperedError,
    PriceMatrix,
    RebalanceEvent,
    WeightConstraintError,
)
from src.racetrack.runner import RunnerContract, RunnerRegistry
from src.racetrack.ledger import EventLedger
from src.racetrack.scoring import evaluate_race_season


@pytest.fixture
def matrix():
    sessions = ("2026-01-02", "2026-01-05")
    return PriceMatrix(
        market="us",
        pool_id="us_selected_equities_v2",
        reference_symbol="QQQ",
        calendar="XNYS",
        start_session=sessions[0],
        end_session=sessions[-1],
        sessions=sessions,
        candidate_symbols=("A",),
        symbols=("A", "QQQ"),
        prices=pd.DataFrame({"A": [100.0, 101.0], "QQQ": [100.0, 100.5]}, index=sessions),
        matrix_sha256="a" * 64,
        source_evidence_hashes={"A": "b" * 64},
        catalog_sha256="c" * 64,
    )


def runner(matrix, *, identity="runner", parent="0" * 64):
    event = RebalanceEvent.create(
        parent_hash=parent,
        effective_session=matrix.sessions[0],
        runner_id=identity,
        runner_version="1",
        target_weights={"A": 1.0},
        reason="Synthetic boundary test",
    )
    return RunnerContract(
        runner_id="runner",
        runner_version="1",
        pool_id=matrix.pool_id,
        benchmark_symbol="QQQ",
        thesis="A synthetic hypothesis to test immutable evidence boundaries.",
        selection_logic="synthetic",
        rebalance_logic="synthetic",
        events_generator=lambda _: [event],
    )


@pytest.mark.parametrize("identity,parent", [("other", "0" * 64), ("runner", "f" * 64)])
def test_invalid_identity_or_chain_cannot_create_ledger(matrix, tmp_path, identity, parent):
    destination = tmp_path / "ledger.jsonl"
    with pytest.raises(LedgerTamperedError):
        runner(matrix, identity=identity, parent=parent).run(matrix, ledger_path=destination)
    assert not destination.exists()


def test_retained_ledger_is_not_overwritten(matrix, tmp_path):
    destination = tmp_path / "ledger.jsonl"
    destination.write_bytes(b"retained evidence")
    original_names = {p.name for p in tmp_path.iterdir()}
    with pytest.raises(LedgerOverwriteError):
        runner(matrix).run(matrix, ledger_path=destination)
    assert destination.read_bytes() == b"retained evidence"
    assert {p.name for p in tmp_path.iterdir()} == original_names


def test_loading_mixed_runner_ledger_rejects_even_valid_hashes(matrix, tmp_path):
    first = runner(matrix).generate_rebalance_events(matrix)[0]
    second = RebalanceEvent.create(
        parent_hash=first.event_hash,
        effective_session=matrix.sessions[1],
        runner_id="other",
        runner_version="1",
        target_weights={"A": 1.0},
        reason="A linked event with the wrong runner",
    )
    destination = tmp_path / "mixed.jsonl"
    destination.write_text(
        "\n".join(json.dumps(event.to_dict()) for event in (first, second)), encoding="utf-8"
    )
    with pytest.raises(LedgerTamperedError):
        EventLedger.load(destination)


def publish(matrix, tmp_path, monkeypatch, **kwargs):
    monkeypatch.setattr(pipeline, "load_price_matrix", lambda **_: matrix)
    return pipeline.publish_racetrack_projection(
        output_dir=tmp_path / "out",
        as_of_cutoff=matrix.end_session,
        root_path=Path(__file__).resolve().parents[1],
        **kwargs,
    )


def test_pointer_failure_preserves_entire_previous_release(matrix, tmp_path, monkeypatch):
    first = publish(matrix, tmp_path, monkeypatch)
    original = {
        p: p.read_bytes()
        for p in (first.manifest_path, first.latest_scoreboard_path, first.archive_scoreboard_path)
    }

    def fail(*_):
        raise OSError("Injected pointer failure")

    monkeypatch.setattr(pipeline.os, "replace", fail)
    with pytest.raises(OSError, match="Injected"):
        publish(matrix, tmp_path, monkeypatch, season_id="changed-vintage")
    for path, data in original.items():
        assert path.read_bytes() == data
    assert not list((tmp_path / "out").glob(".staging_*"))
    assert not list((tmp_path / "out").glob(".manifest_*.tmp"))
    assert "diagnostic_baseline_only" in pipeline.render_racetrack_scoreboard(tmp_path / "out")


def test_same_session_new_vintage_and_idempotent_rerun(matrix, tmp_path, monkeypatch):
    first = publish(matrix, tmp_path, monkeypatch)
    original_archive = first.archive_scoreboard_path.read_bytes()
    repeated = publish(matrix, tmp_path, monkeypatch)
    assert repeated.archive_scoreboard_path == first.archive_scoreboard_path
    changed = publish(matrix, tmp_path, monkeypatch, config=EngineConfig(friction_rate=0.0015))
    assert changed.latest_scoreboard_path != first.latest_scoreboard_path
    assert first.archive_scoreboard_path.read_bytes() == original_archive
    assert len(list((tmp_path / "out" / "versions").iterdir())) == 2


def test_runner_detail_is_hash_bound_to_same_replay(matrix, tmp_path, monkeypatch):
    contract = runner(matrix)
    registry = RunnerRegistry(candidate_symbols=matrix.candidate_symbols)
    registry.register(contract)
    result = publish(matrix, tmp_path, monkeypatch, registry=registry)
    key = result.manifest_dict["runner_details"][contract.runner_id]
    artifact = result.manifest_dict["artifacts"][key]
    path = result.manifest_path.parent / artifact["path"]
    detail = json.loads(path.read_text(encoding="utf-8"))
    assert pipeline.compute_file_sha256(path) == artifact["sha256"]
    assert path.stat().st_size == artifact["size_bytes"]
    assert detail["thesis"] == contract.thesis
    assert detail["selection_logic"] == contract.selection_logic
    assert detail["runner_version"] == contract.runner_version
    assert detail["as_of_session"] == matrix.end_session
    assert detail["model_weights"] == [{"symbol": "A", "weight": 1.0}]
    assert detail["rebalance_history"] is None
    assert detail["association_evidence"] is None
    assert detail["research_only"] is True and detail["trade_ready"] is False


def test_detail_change_beyond_summary_creates_new_vintage(matrix, tmp_path, monkeypatch):
    contract = runner(matrix)
    contract.thesis = "A" * 120 + " original complete thesis"
    registry = RunnerRegistry(candidate_symbols=matrix.candidate_symbols)
    registry.register(contract)
    first = publish(matrix, tmp_path, monkeypatch, registry=registry)
    original = first.latest_scoreboard_path.read_bytes()
    contract.thesis = "A" * 120 + " amended complete thesis"
    second = publish(matrix, tmp_path, monkeypatch, registry=registry)
    assert first.scoreboard.entries[0].thesis_summary == second.scoreboard.entries[0].thesis_summary
    assert first.latest_scoreboard_path != second.latest_scoreboard_path
    assert first.latest_scoreboard_path.read_bytes() == original
    ref = first.manifest_dict["artifacts"][
        first.manifest_dict["runner_details"][contract.runner_id]
    ]
    retained = first.manifest_path.parent / ref["path"]
    retained.write_text("{}", encoding="utf-8")
    contract.thesis = "A" * 120 + " original complete thesis"
    with pytest.raises(ValueError, match="Existing release differs"):
        publish(matrix, tmp_path, monkeypatch, registry=registry)


@pytest.mark.parametrize("damage", ["hash", "market", "escape", "version"])
def test_reader_rejects_broken_or_wrong_identity(matrix, tmp_path, monkeypatch, damage):
    result = publish(matrix, tmp_path, monkeypatch)
    manifest = result.manifest_dict
    if damage == "hash":
        result.latest_scoreboard_path.write_text("{}", encoding="utf-8")
    elif damage == "market":
        manifest["market"] = "cn"
    elif damage == "escape":
        manifest["artifacts"]["scoreboard_latest"]["path"] = "../outside.json"
    else:
        manifest["pipeline_version"] = "unrecognized"
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline.render_racetrack_scoreboard(tmp_path / "out", market="us")


def test_partial_runner_calendar_is_rejected(matrix):
    simulation = runner(matrix).run(matrix)
    partial = replace(simulation, nav_history=simulation.nav_history[1:])
    with pytest.raises(CalendarSessionError):
        evaluate_race_season({}, {"runner": partial}, simulation, simulation)


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -0.1, 1.0])
def test_invalid_cost_is_rejected(cost):
    with pytest.raises(ValueError):
        EngineConfig(friction_rate=cost)


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -0.1])
def test_invalid_weights_are_rejected(weight):
    with pytest.raises(WeightConstraintError):
        RebalanceEvent.create(
            parent_hash="0" * 64,
            effective_session="2026-01-02",
            runner_id="runner",
            runner_version="1",
            target_weights={"A": weight},
            reason="Invalid allocation",
        )
