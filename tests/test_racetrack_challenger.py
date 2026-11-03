"""Tests for Issue #1358: Genuinely independent US87 challenger runner."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.racetrack.challenger import (
    US87_LOW_VOL_REBALANCE,
    US87_LOW_VOL_RUNNER_ID,
    US87_LOW_VOL_RUNNER_VERSION,
    US87_LOW_VOL_SELECTION,
    US87_LOW_VOL_THESIS,
    compute_realized_volatility,
    create_us_low_vol_runner,
    generate_low_vol_events,
    simulate_us_low_vol_challenger,
)
from src.racetrack.contracts import (
    EngineConfig,
    PriceMatrix,
    RebalanceEvent,
    Scoreboard,
    UnauthorizedAssetError,
)
from src.racetrack.ledger import EventLedger
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerRegistry, create_us_pool_runner, validate_runner_thesis


def create_mock_price_matrix(sessions, candidate_symbols, prices_dict):
    """Helper creating a test PriceMatrix."""
    prices_df = pd.DataFrame(prices_dict, index=list(sessions))
    symbols = tuple(list(candidate_symbols) + ["QQQ"])
    return PriceMatrix(
        market="us",
        pool_id="us_selected_equities_v2",
        reference_symbol="QQQ",
        calendar="XNYS",
        start_session=sessions[0],
        end_session=sessions[-1],
        sessions=tuple(sessions),
        candidate_symbols=tuple(candidate_symbols),
        symbols=symbols,
        prices=prices_df,
        matrix_sha256="m" * 64,
        source_evidence_hashes={},
    )


def test_challenger_thesis_and_contract_metadata():
    """Verify challenger runner conforms to runner requirements and substantive thesis rules."""
    runner = create_us_low_vol_runner()
    assert runner.runner_id == US87_LOW_VOL_RUNNER_ID
    assert runner.runner_version == US87_LOW_VOL_RUNNER_VERSION
    assert runner.pool_id == "us_selected_equities_v2"
    assert runner.benchmark_symbol == "QQQ"
    # Thesis validation: must have >= 30 chars and not contain 'TODO' / 'placeholder'
    validate_runner_thesis(runner.thesis)
    assert len(runner.thesis) >= 30
    assert len(runner.selection_logic) >= 30
    assert len(runner.rebalance_logic) >= 30
    assert "lowest-realized-volatility" in runner.thesis
    assert "20-session" in runner.selection_logic
    assert "friction" in runner.rebalance_logic


def test_compute_realized_volatility_mathematical_properties():
    """Verify annualized realized volatility calculation logic and boundary handling."""
    # Constant price sequence -> 0.0 volatility
    assert compute_realized_volatility(np.array([100.0, 100.0, 100.0, 100.0])) == pytest.approx(0.0)

    # Insufficient observations (< 2)
    assert np.isnan(compute_realized_volatility(np.array([100.0])))
    assert np.isnan(compute_realized_volatility(np.array([])))

    # Non-positive or NaN values disqualified
    assert np.isnan(compute_realized_volatility(np.array([100.0, np.nan, 105.0])))
    assert np.isnan(compute_realized_volatility(np.array([100.0, 0.0, 105.0])))
    assert np.isnan(compute_realized_volatility(np.array([100.0, -10.0, 105.0])))

    # Known standard sequence
    prices = np.array([100.0, 102.0, 101.0, 103.0, 102.5])
    log_ret = np.diff(np.log(prices))
    expected_vol = float(np.std(log_ret, ddof=1) * np.sqrt(252.0))
    assert compute_realized_volatility(prices) == pytest.approx(expected_vol)


def test_challenger_selection_independence_and_cash_buffer():
    """Verify challenger independently selects lowest volatility assets and uses cash buffering."""
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    # September has 21 sessions, October has 19 sessions (up to Oct 27)
    sessions = tuple(str(d.date()) for d in calendar.sessions_in_range("2026-09-01", "2026-10-27"))

    # Construct 4 candidates:
    # A: high volatility (alternating +/- 4%)
    # B: low volatility (smooth +/- 0.1%)
    # C: medium volatility (alternating +/- 1.5%)
    # D: NaN in September (short history / missing data)
    n = len(sessions)
    a_prices = [100.0 * (1.04 if i % 2 == 1 else 0.96) for i in range(n)]
    b_prices = [100.0 * (1.001 if i % 2 == 1 else 0.999) for i in range(n)]
    c_prices = [100.0 * (1.015 if i % 2 == 1 else 0.985) for i in range(n)]
    d_prices = [np.nan if i < 25 else 50.0 for i in range(n)]
    qqq_prices = [100.0] * n

    candidates = ["A", "B", "C", "D"]
    prices_dict = {"A": a_prices, "B": b_prices, "C": c_prices, "D": d_prices, "QQQ": qqq_prices}
    matrix = create_mock_price_matrix(sessions, candidates, prices_dict)

    # Generate events with top_k=2, lookback_sessions=20
    events = generate_low_vol_events(matrix, top_k=2, lookback_sessions=20)

    # There should be 2 rebalance events: 2026-09-01 and 2026-10-01
    assert len(events) == 2
    ev_sep = events[0]
    ev_oct = events[1]

    assert ev_sep.effective_session == "2026-09-01"
    # Month 1 is burn-in (< 20 lookback sessions available), so 100% cash
    assert ev_sep.target_weights == {}
    assert ev_sep.cash_weight == 1.0

    assert ev_oct.effective_session == "2026-10-01"
    # Month 2 has 21 sessions of September data.
    # Lowest volatility should be B, then C, then A. D is disqualified due to NaNs.
    # Top 2 selected: B and C.
    assert set(ev_oct.target_weights.keys()) == {"B", "C"}
    assert ev_oct.target_weights["B"] == pytest.approx(0.5)
    assert ev_oct.target_weights["C"] == pytest.approx(0.5)
    assert ev_oct.cash_weight == 0.0

    # Independence check: challenger weights != equal weight pool index
    pool_runner = create_us_pool_runner()
    pool_events = pool_runner.events_generator(matrix)
    # Pool index weights all available candidates ("A", "B", "C") equally (1/3 each)
    pool_oct_ev = next(e for e in pool_events if e.effective_session == "2026-10-01")
    assert pool_oct_ev.target_weights != ev_oct.target_weights


def test_challenger_zero_lookahead_discipline():
    """Verify trailing volatility estimate uses ONLY sessions strictly prior to rebalance date."""
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    sessions = tuple(str(d.date()) for d in calendar.sessions_in_range("2026-09-01", "2026-10-27"))
    n = len(sessions)

    # Base price setup
    a_prices = [100.0 * (1.02 if i % 2 == 1 else 0.98) for i in range(n)]
    b_prices = [100.0 * (1.001 if i % 2 == 1 else 0.999) for i in range(n)]
    qqq_prices = [100.0] * n

    matrix1 = create_mock_price_matrix(
        sessions, ["A", "B"], {"A": list(a_prices), "B": list(b_prices), "QQQ": qqq_prices}
    )

    # Mutate price on October 1st (session 21) for candidate B: dramatic shock!
    # If the selection at Oct 1 looks ahead to Oct 1 price for volatility, it will change.
    # But strict PIT only uses sessions 1..20 (September).
    oct1_idx = sessions.index("2026-10-01")
    b_prices_mutated = list(b_prices)
    b_prices_mutated[oct1_idx] = 999.0  # huge spike on rebalance day itself

    matrix2 = create_mock_price_matrix(
        sessions, ["A", "B"], {"A": list(a_prices), "B": b_prices_mutated, "QQQ": qqq_prices}
    )

    events1 = generate_low_vol_events(matrix1, top_k=1, lookback_sessions=20)
    events2 = generate_low_vol_events(matrix2, top_k=1, lookback_sessions=20)

    # Selection at 2026-10-01 must be completely identical between both matrices!
    assert events1[1].effective_session == events2[1].effective_session == "2026-10-01"
    assert events1[1].target_weights == events2[1].target_weights


def test_challenger_deterministic_simulation_and_q_ledger(tmp_path: Path):
    """Verify challenger simulation reproducibility and cryptographic ledger hash chain."""
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    sessions = tuple(str(d.date()) for d in calendar.sessions_in_range("2026-09-01", "2026-10-27"))
    n = len(sessions)
    prices_dict = {
        "A": [100.0 * (1.002 ** i) for i in range(n)],
        "B": [100.0 * (0.998 ** i) for i in range(n)],
        "QQQ": [100.0] * n,
    }
    matrix = create_mock_price_matrix(sessions, ["A", "B"], prices_dict)
    runner = create_us_low_vol_runner(lookback_sessions=20, top_k=1)

    ledger_path1 = tmp_path / "ledger1.jsonl"
    ledger_path2 = tmp_path / "ledger2.jsonl"

    res1 = runner.run(matrix, ledger_path=ledger_path1)
    res2 = runner.run(matrix, ledger_path=ledger_path2)

    # Bitwise identical NAV series
    assert res1.nav_history == res2.nav_history
    assert res1.runner_id == US87_LOW_VOL_RUNNER_ID
    assert res1.cumulative_return == res2.cumulative_return

    # Cryptographic ledger verification
    bytes1 = ledger_path1.read_bytes()
    bytes2 = ledger_path2.read_bytes()
    assert bytes1 == bytes2

    ledger = EventLedger.load(ledger_path1)
    assert ledger.runner_id == US87_LOW_VOL_RUNNER_ID
    assert len(ledger.events) == 2
    assert ledger.events[-1].event_hash == ledger.tip_hash
    assert ledger.events[0].parent_hash == "0" * 64
    assert ledger.events[1].parent_hash == ledger.events[0].event_hash


def test_challenger_negative_boundaries_and_rejections(tmp_path: Path):
    """Verify negative boundaries: market mismatch, unauthorized asset injection, ledger tampering."""
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    sessions = tuple(str(d.date()) for d in calendar.sessions_in_range("2026-09-01", "2026-09-10"))
    matrix = create_mock_price_matrix(
        sessions, ["A", "B"], {"A": [100.0] * len(sessions), "B": [100.0] * len(sessions), "QQQ": [100.0] * len(sessions)}
    )

    runner = create_us_low_vol_runner()

    # 1. Pool ID mismatch raises ValueError
    cn_matrix = replace(matrix, pool_id="cn_selected_equities_v3", market="cn")
    with pytest.raises(ValueError, match="pool_id"):
        runner.run(cn_matrix)

    # 2. Rejection of unauthorized asset injection (asset outside matrix universe)
    unauthorized_event = RebalanceEvent.create(
        parent_hash="0" * 64,
        effective_session=sessions[0],
        runner_id=runner.runner_id,
        runner_version=runner.runner_version,
        target_weights={"UNKNOWN_STOCK": 0.5, "A": 0.5},
        reason="Test unauthorized injection",
    )
    from src.racetrack.engine import simulate_portfolio

    with pytest.raises(UnauthorizedAssetError):
        simulate_portfolio(matrix, [unauthorized_event])

    # 3. Tampered ledger detection
    ledger_path = tmp_path / "ledger_tamper.jsonl"
    runner.run(matrix, ledger_path=ledger_path)
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    # Mutate cash_weight in the first event JSON without updating event_hash
    first_ev = json.loads(lines[0])
    first_ev["cash_weight"] = 0.5  # tamper with payload
    lines[0] = json.dumps(first_ev)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from src.racetrack.contracts import LedgerTamperedError

    with pytest.raises(LedgerTamperedError):
        EventLedger.load(ledger_path)


def test_end_to_end_publish_with_challenger_and_benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """Verify full end-to-end atomic publish with both pool benchmark and independent challenger."""
    from src.racetrack import pipeline
    from tests.test_racetrack_first_season import season_fixture

    source, _, _, _ = season_fixture()
    monkeypatch.setattr(pipeline, "load_price_matrix", lambda **_: source)

    for p in [
        f"configs/research_universes/{source.pool_id}.yaml",
        "configs/pools/selected_pool_registry_v1.yaml",
        "configs/pools/reference_instrument_registry_v1.yaml",
    ]:
        target = tmp_path / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic identity")

    result = pipeline.publish_racetrack_projection(
        root_path=tmp_path,
        as_of_cutoff="2026-10-27",
        with_pool_runner=True,
        with_challenger_runner=True,
    )

    manifest = result.manifest_dict
    assert manifest["pipeline_version"] == "2.0.0"
    assert result.runner_count == 2
    assert len(result.scoreboard.entries) == 2

    # Verify runner identities in scoreboard
    runner_ids = {e.runner_id for e in result.scoreboard.entries}
    assert runner_ids == {"us87_ew_pool_runner_v1", "us87_low_vol_challenger_v1"}

    # Verify first-season roles in scoreboard and manifest
    roles = result.scoreboard.first_season["roles"]
    assert roles["us87_ew_pool_runner_v1"] == "internal_benchmark_racer"
    assert roles["us87_low_vol_challenger_v1"] == "strategy_racer"

    # Verify retained local evidence contains valid Q-ledgers for BOTH runners
    assert set(manifest["local_evidence"].keys()) == runner_ids
    root = result.manifest_path.parent
    for r_id in runner_ids:
        evidence = manifest["local_evidence"][r_id]
        ledger_path = root / evidence["path"]
        assert ledger_path.exists()
        ledger = EventLedger.load(ledger_path)
        assert ledger.runner_id == r_id
        assert ledger.tip_hash == evidence["tip_hash"]
        assert len(ledger.events) == evidence["event_count"]
        assert pipeline.compute_file_sha256(ledger_path) == evidence["sha256"]

    # Verify runner detail artifacts
    for r_id in runner_ids:
        detail_key = manifest["runner_details"][r_id]
        detail_file = root / manifest["artifacts"][detail_key]["path"]
        detail = json.loads(detail_file.read_text(encoding="utf-8"))
        assert detail["runner_id"] == r_id
        assert detail["schema_version"] == "2.0"
        assert detail["research_only"] is True
        assert detail["trade_ready"] is False
        if r_id == "us87_ew_pool_runner_v1":
            assert detail["runner_role"] == "internal_benchmark_racer"
        else:
            assert detail["runner_role"] == "strategy_racer"

    # Verify scoreboard rendering formats: json, table, markdown
    json_out = pipeline.render_racetrack_scoreboard(root, "json")
    parsed_json = json.loads(json_out)
    assert len(parsed_json["entries"]) == 2

    table_out = pipeline.render_racetrack_scoreboard(root, "table")
    assert "us87_ew_pool_runner_v1" in table_out
    assert "us87_low_vol_challenger_v1" in table_out

    md_out = pipeline.render_racetrack_scoreboard(root, "markdown")
    assert "us87_ew_pool_runner_v1" in md_out
    assert "us87_low_vol_challenger_v1" in md_out

    # CLI test with --with-challenger-runner
    from src.cli.main import main

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "racetrack",
            "publish",
            "--with-challenger-runner",
            "--as-of",
            "2026-10-27",
        ]
    )
    assert exit_code == 0
    cli_output = json.loads(capsys.readouterr().out)
    assert cli_output["status"] == "published"
    assert cli_output["runner_count"] == 2


def test_challenger_rejects_cn_market():
    """Verify that challenger runner explicitly rejects CN market."""
    from src.racetrack.pipeline import publish_racetrack_projection

    with pytest.raises(ValueError, match="Issue #1358"):
        publish_racetrack_projection(market="cn", with_challenger_runner=True)
