"""First-season contracts: real pool evidence, versioned scoring and publication."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.racetrack.contracts import EngineConfig, PriceMatrix, RebalanceEvent, Scoreboard
from src.racetrack.ledger import EventLedger
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerContract, RunnerRegistry, create_us_pool_runner
from src.racetrack.scoring import PointsRuleV1, ReturnPointsV2, evaluate_first_season, generate_benchmark_simulation


def matrix(sessions=("2026-09-30", "2026-10-01", "2026-10-02")):
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0], "B": [np.nan, 200.0, 180.0],
        "QQQ": [100.0, 101.0, 102.0]}, index=list(sessions))
    return PriceMatrix(market="us", pool_id="us_selected_equities_v2", reference_symbol="QQQ",
        calendar="XNYS", start_session=sessions[0], end_session=sessions[-1], sessions=sessions,
        candidate_symbols=("A", "B"), symbols=("A", "B", "QQQ"), prices=prices,
        matrix_sha256="a" * 64, source_evidence_hashes={})


def test_pool_racer_reconciles_exactly_and_retains_owned_q_ledger(tmp_path: Path):
    source = matrix()
    runner = create_us_pool_runner()
    registry = RunnerRegistry(candidate_symbols=source.candidate_symbols)
    registry.register(runner)
    path = tmp_path / "pool.jsonl"
    result = runner.run(source, ledger_path=path)
    benchmark = generate_equal_weight_pool_index(source, source.pool_id)
    assert result.runner_id == "us87_ew_pool_runner_v1"
    assert result.runner_id != benchmark.runner_id
    assert result.nav_history == benchmark.nav_history
    ledger = EventLedger.load(path)
    assert ledger.runner_id == runner.runner_id
    assert len(ledger.events) == 2
    assert ledger.events[0].cash_weight == .5
    assert ledger.events[1].cash_weight == 0
    assert ledger.events[-1].event_hash == ledger.tip_hash


def test_us_pool_racer_rejects_cross_market_and_preserves_friction():
    source = matrix()
    runner = create_us_pool_runner()
    with pytest.raises(ValueError, match="pool_id"):
        runner.run(replace(source, pool_id="cn_selected_equities_v3", market="cn"))
    result = runner.run(source, config=EngineConfig(friction_rate=.0008))
    assert result.nav_history[0].nav == pytest.approx(1 - .5 * .0008)


def season_fixture():
    import exchange_calendars as xcals
    dates = tuple(str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range("2026-09-01", "2026-10-27"))
    prices = pd.DataFrame({"A": [100 * 1.002 ** i for i in range(len(dates))],
        "B": [100 * .998 ** i for i in range(len(dates))], "QQQ": [100.] * len(dates)}, index=dates)
    source = replace(matrix(), start_session=dates[0], end_session=dates[-1], sessions=dates, prices=prices)
    pool = create_us_pool_runner()
    runners = {pool.runner_id: pool}
    for key, symbol in [("up", "A"), ("up_tie", "A"), ("down", "B")]:
        runners[key] = RunnerContract(key, "1.0.0", source.pool_id, "QQQ",
            "Synthetic test-only buy and hold thesis, not a real admitted season competitor.", "one symbol", "hold",
            events_generator=lambda m, key=key, symbol=symbol: [RebalanceEvent.create(
                parent_hash="0" * 64, effective_session=m.sessions[0], runner_id=key,
                runner_version="1.0.0", target_weights={symbol: 1.}, reason="Synthetic fixture only")])
    simulations = {key: runner.run(source) for key, runner in runners.items()}
    return source, runners, simulations, pool.runner_id


def test_v2_negative_return_points_true_window_ties_and_complete_history():
    source, runners, simulations, pool_id = season_fixture()
    board = evaluate_first_season(runners, simulations, generate_benchmark_simulation(source),
        simulations[pool_id], "season_us_2026_10", source.pool_id, "QQQ", "XNYS", pool_id)
    entries = {e.runner_id: e for e in board.entries}
    assert board.schema_version == "2.0"
    assert PointsRuleV1.get_points(1) == 10  # frozen old rule
    assert ReturnPointsV2.get_points(-.015) == -1.5
    assert entries["down"].season_points < 0
    assert entries["up"].season_points == entries["up_tie"].season_points
    assert entries["up"].current_rank == entries["up_tie"].current_rank == 1
    assert entries[pool_id].current_rank == 3
    for entry in entries.values():
        assert entry.cumulative_points == pytest.approx(sum(p.monthly_net_return * 100 for p in entry.monthly_ranks))
    assert entries["up"].cumulative_points != pytest.approx(simulations["up"].cumulative_return * 100)
    window = board.first_season["windows"]["1"]
    assert window["anchor_session"] == "2026-09-25"  # Sunday calendar duration anchors to previous session
    assert window["ranks"]["up"] == window["ranks"]["up_tie"] == 1
    assert board.first_season["windows"]["3"]["ranks"]["up"] is None
    assert board.first_season["windows"]["3"]["top_runner_ids"] == []
    assert entries["up"].return_3m is None  # two partial buckets cannot become three months
    months = board.first_season["month_windows"]
    assert months[0]["complete_window"] is True
    assert months[1]["complete_window"] is False
    assert all(m["settlement_status"] == "not_reviewed" for m in months)
    assert board.first_season["season_state"] == "provisional"
    assert entries[pool_id].excess_vs_pool == 0
    assert Scoreboard.from_json(board.to_json()).to_dict() == board.to_dict()


def test_v2_rejects_gapped_calendar_even_when_legacy_series_align():
    source, runners, simulations, pool_id = season_fixture()
    simulations = {key: replace(sim, nav_history=sim.nav_history[:3] + sim.nav_history[4:]) for key, sim in simulations.items()}
    with pytest.raises(ValueError, match="missing or unofficial"):
        evaluate_first_season(runners, simulations, simulations[pool_id], simulations[pool_id],
            "season_us_2026_10", source.pool_id, "QQQ", "XNYS", pool_id)


def test_window_ranking_can_differ_from_current_month_points():
    source, runners, _, pool_id = season_fixture()
    september_count = sum(d.startswith("2026-09") for d in source.sessions)
    a = [100 * 1.03 ** min(i, september_count - 1) * .999 ** max(0, i - september_count + 1) for i in range(len(source.sessions))]
    b = [100 * .97 ** min(i, september_count - 1) * 1.001 ** max(0, i - september_count + 1) for i in range(len(source.sessions))]
    source = replace(source, prices=pd.DataFrame({"A": a, "B": b, "QQQ": [100.] * len(a)}, index=source.sessions))
    simulations = {key: runner.run(source) for key, runner in runners.items()}
    board = evaluate_first_season(runners, simulations, generate_benchmark_simulation(source),
        simulations[pool_id], "season_us_2026_10", source.pool_id, "QQQ", "XNYS", pool_id)
    assert board.entries[0].runner_id == "down"  # October winner
    assert board.first_season["windows"]["1"]["top_runner_ids"][0] == "up"  # trailing window includes late September


@pytest.mark.parametrize("damage", ["anchor", "season"])
def test_v2_rejects_nonpositive_anchor_and_wrong_season_identity(damage):
    source, runners, simulations, pool_id = season_fixture()
    season = "season_us_2026_09" if damage == "season" else "season_us_2026_10"
    if damage == "anchor":
        sim = simulations["up"]
        points = list(sim.nav_history)
        index = source.sessions.index("2026-09-25")
        points[index] = replace(points[index], nav=0.)
        simulations["up"] = replace(sim, nav_history=tuple(points))
    with pytest.raises(ValueError, match="anchor|current natural calendar month"):
        evaluate_first_season(runners, simulations, generate_benchmark_simulation(source),
            simulations[pool_id], season, source.pool_id, "QQQ", "XNYS", pool_id)


def test_v2_publication_retains_ledger_once_and_tamper_cannot_advance_pointer(tmp_path, monkeypatch, capsys):
    from src.racetrack import pipeline
    source, _, _, runner_id = season_fixture()
    monkeypatch.setattr(pipeline, "load_price_matrix", lambda **_: source)
    for path in [f"configs/research_universes/{source.pool_id}.yaml",
        "configs/pools/selected_pool_registry_v1.yaml", "configs/pools/reference_instrument_registry_v1.yaml"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic identity")
    original_run = RunnerContract.run
    calls = []
    def counted_run(self, *args, **kwargs):
        calls.append(self.runner_id)
        return original_run(self, *args, **kwargs)
    monkeypatch.setattr(RunnerContract, "run", counted_run)
    result = pipeline.publish_racetrack_projection(root_path=tmp_path, as_of_cutoff="2026-10-27", with_pool_runner=True)
    assert calls == [runner_id]
    assert result.manifest_dict["pipeline_version"] == "2.0.0"
    assert result.runner_count == 1
    assert result.scoreboard.benchmarks["pool_index"] == result.scoreboard.top_runners_nav[runner_id]
    evidence = result.manifest_dict["local_evidence"][runner_id]
    root = result.manifest_path.parent
    assert pipeline.compute_file_sha256(result.manifest_path) == result.manifest_sha256
    assert (root / "versions" / result.manifest_dict["release_id"] / "manifest.json").read_bytes() == result.manifest_path.read_bytes()
    ledger = EventLedger.load(root / evidence["path"])
    assert evidence["event_count"] == len(ledger.events) == 2
    assert evidence["tip_hash"] == ledger.tip_hash
    assert pipeline.compute_file_sha256(root / evidence["path"]) == evidence["sha256"]
    assert not any(ref["path"].endswith(".jsonl") for ref in result.manifest_dict["artifacts"].values())
    assert pipeline.render_racetrack_scoreboard(root, "json")
    assert "prior-close anchor" in pipeline.render_racetrack_scoreboard(root, "table")
    assert "arithmetic point totals are not compounded" in pipeline.render_racetrack_scoreboard(root, "markdown")
    detail_key = result.manifest_dict["runner_details"][runner_id]
    detail = json.loads((root / result.manifest_dict["artifacts"][detail_key]["path"]).read_text())
    assert detail["runner_role"] == "internal_benchmark_racer"
    assert detail["schema_version"] == "2.0"
    pointer = result.manifest_path.read_bytes()
    repeat = pipeline.publish_racetrack_projection(root_path=tmp_path, as_of_cutoff="2026-10-27", with_pool_runner=True)
    assert repeat.manifest_dict["release_id"] == result.manifest_dict["release_id"]
    assert repeat.manifest_path.read_bytes() == pointer
    from src.cli.main import main
    assert main(["--root", str(tmp_path), "racetrack", "publish", "--with-pool-runner", "--as-of", "2026-10-27"]) == 0
    assert json.loads(capsys.readouterr().out)["runner_count"] == 1
    (root / evidence["path"]).write_bytes(b"tampered retained evidence")
    with pytest.raises(ValueError, match="hash/size"):
        pipeline.render_racetrack_scoreboard(root, "json")
    with pytest.raises(ValueError, match="content identity"):
        pipeline.publish_racetrack_projection(root_path=tmp_path, as_of_cutoff="2026-10-27", with_pool_runner=True)
    assert result.manifest_path.read_bytes() == pointer
    assert not list(root.glob(".staging_*"))


def test_phase_a_does_not_silently_admit_cn_or_external_registry():
    from src.racetrack.pipeline import publish_racetrack_projection
    with pytest.raises(ValueError, match="Phase A"):
        publish_racetrack_projection(market="cn", with_pool_runner=True)
    with pytest.raises(ValueError, match="Phase A"):
        publish_racetrack_projection(with_pool_runner=True, registry=RunnerRegistry(candidate_symbols=("A",)))


@pytest.mark.parametrize("damage", ["missing_q", "schema", "points_rule", "period", "q_identity", "q_tip"])
def test_python_reader_rejects_hash_valid_but_inconsistent_v2_contract(tmp_path, monkeypatch, damage):
    from src.racetrack import pipeline
    source, _, _, _ = season_fixture()
    monkeypatch.setattr(pipeline, "load_price_matrix", lambda **_: source)
    for path in [f"configs/research_universes/{source.pool_id}.yaml",
        "configs/pools/selected_pool_registry_v1.yaml", "configs/pools/reference_instrument_registry_v1.yaml"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic identity")
    result = pipeline.publish_racetrack_projection(root_path=tmp_path, as_of_cutoff="2026-10-27", with_pool_runner=True)
    manifest = result.manifest_dict
    if damage == "missing_q":
        manifest.pop("local_evidence")
    elif damage == "q_identity":
        manifest["local_evidence"]["wrong"] = manifest["local_evidence"].pop(next(iter(manifest["local_evidence"])))
    elif damage == "q_tip":
        next(iter(manifest["local_evidence"].values()))["tip_hash"] = "f" * 64
    else:
        payload = json.loads(result.latest_scoreboard_path.read_text())
        if damage == "schema":
            payload["schema_version"] = "1.0"
            payload.pop("first_season")
        elif damage == "points_rule":
            payload["first_season"]["points_rule"] = "rank_points_v1"
        else:
            payload["period_policy"] = "calendar_month_buckets_including_partial"
        result.latest_scoreboard_path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        manifest["artifacts"]["scoreboard_latest"].update(
            sha256=pipeline.compute_file_sha256(result.latest_scoreboard_path),
            size_bytes=result.latest_scoreboard_path.stat().st_size)
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        pipeline.render_racetrack_scoreboard(result.manifest_path.parent, "json")
