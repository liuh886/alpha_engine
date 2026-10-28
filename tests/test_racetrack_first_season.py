"""First-season contracts: real pool evidence, versioned scoring and publication."""
from dataclasses import replace
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
