"""First-season contracts: real pool evidence, versioned scoring and publication."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.racetrack.contracts import EngineConfig, PriceMatrix
from src.racetrack.ledger import EventLedger
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerRegistry, create_us_pool_runner


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
