"""Tests for RI-04 / B3: Dual-consumer research reuse experiment.

Governed under Track B (#1296) and ADR-0005.
Verifies that CN cross-sectional factor ranking and A-Share RDI event readiness
share the exact same data slice reader, PIT boundaries, and cryptographic receipts.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.data.research_slice import DataSliceRequest
from src.research.ashare_rdi.contracts import RiskEvent
from src.research.dual_consumer_reuse_experiment import (
    run_cn_cross_sectional_research_experiment,
    run_rdi_event_horizon_readiness_experiment,
)

ROOT = Path(__file__).resolve().parents[1]


def test_ri04_consumer1_cross_sectional_happy_path_deterministic() -> None:
    """Consumer 1 Happy Path: CN 4 equities evaluated deterministically."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001", "000338", "600519", "688008"),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
        required_fields=("open", "high", "low", "close", "volume"),
    )

    res1 = run_cn_cross_sectional_research_experiment(req, root=ROOT)
    assert res1["consumer"] == "cn_cross_sectional_research"
    assert res1["status"] == "ready"
    assert res1["evaluation_time"] == "2026-09-04"
    assert res1["data_slice_receipt"]["status"] == "ready"
    assert res1["data_slice_receipt"]["total_rows"] == 2596

    rankings = res1["rankings"]
    assert len(rankings) == 4
    # Verify rank 1 to 4 coverage
    assigned_ranks = {v["rank"] for v in rankings.values()}
    assert assigned_ranks == {1, 2, 3, 4}

    # Verify rank order: 000001 highest momentum, 688008 lowest
    assert rankings["000001"]["rank"] == 1
    assert rankings["600519"]["rank"] == 2
    assert rankings["000338"]["rank"] == 3
    assert rankings["688008"]["rank"] == 4

    # Repeat run to assert cryptographic experiment hash determinism
    res2 = run_cn_cross_sectional_research_experiment(req, root=ROOT)
    assert res1["experiment_hash"] == res2["experiment_hash"]
    assert res1["data_slice_receipt"]["data_hash"] == res2["data_slice_receipt"]["data_hash"]
    assert res1["experiment_hash"] is not None


def test_ri04_consumer1_cross_sectional_blocked_fail_closed() -> None:
    """Consumer 1 Blocked Path: Jinpan 688676 future dividend aborts ranking fail-closed."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("688676",),
        start_date="2024-01-01",
        end_date="2026-10-15",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    res = run_cn_cross_sectional_research_experiment(req, root=ROOT)
    assert res["consumer"] == "cn_cross_sectional_research"
    assert res["status"] == "blocked"
    assert res["rankings"] is None
    assert res["experiment_hash"] is None
    assert "fail-closed" in res["reason"]

    # Verify underlying receipt carried PIT blocker codes
    blocker_codes = {b["code"] for b in res["data_slice_receipt"]["blocked_reasons"]}
    assert "PIT_VIOLATION_LOOKAHEAD_CUTOFF" in blocker_codes
    assert "PIT_VIOLATION_FUTURE_EVENT_ANNOUNCEMENT" in blocker_codes


def test_ri04_consumer2_rdi_missing_event_blocks_fail_closed() -> None:
    """Consumer 2 #1272 Contract: Missing event source strictly fails closed."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000300",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    res = run_rdi_event_horizon_readiness_experiment(
        req,
        event=None,  # No verified event bound
        root=ROOT,
    )
    assert res["consumer"] == "ashare_rdi_readiness"
    assert res["status"] == "blocked"
    assert "blocked_event_pit_coverage" in res["reason"]
    assert res["outcomes"] is None


def test_ri04_consumer2_rdi_event_available_after_cutoff_blocks_lookahead() -> None:
    """Consumer 2 PIT lookahead: Event available after cutoff fails closed."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000300",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    future_event = RiskEvent(
        event_id="macro-risk-policy-20260910",
        story_id="story-macro-pboc-2026",
        family="policy_easing",
        direction="policy",
        scope="market",
        sector_id=None,
        stage="announced",
        announced_at=datetime(2026, 9, 9, 18, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),  # After cutoff 2026-09-04
        active_from=date(2026, 9, 10),
        active_until=date(2026, 9, 30),
        source_id="gov://pbc.gov.cn/notice/2026-0909",
        source_hash="b" * 64,
    )

    res = run_rdi_event_horizon_readiness_experiment(
        req,
        event=future_event,
        root=ROOT,
    )
    assert res["consumer"] == "ashare_rdi_readiness"
    assert res["status"] == "blocked"
    assert "lookahead event evaluation is strictly forbidden" in res["reason"]


def test_ri04_consumer2_rdi_event_horizon_happy_path_deterministic() -> None:
    """Consumer 2 Happy Path: CSI300 historical event (2024-05-10) evaluates 7/14/28 horizons."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000300",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    audited_event = RiskEvent(
        event_id="macro-risk-policy-20240510",
        story_id="story-macro-pboc-2024",
        family="policy_easing",
        direction="policy",
        scope="market",
        sector_id=None,
        stage="announced",
        announced_at=datetime(2024, 5, 9, 18, 0, tzinfo=timezone.utc),
        available_at=datetime(2024, 5, 9, 20, 0, tzinfo=timezone.utc),
        active_from=date(2024, 5, 10),
        active_until=date(2024, 6, 20),
        source_id="gov://pbc.gov.cn/notice/2024-0509",
        source_hash="a" * 64,
    )

    res1 = run_rdi_event_horizon_readiness_experiment(
        req,
        event=audited_event,
        horizons=(7, 14, 28),
        root=ROOT,
    )
    assert res1["consumer"] == "ashare_rdi_readiness"
    assert res1["status"] == "ready"
    assert res1["decision_session"] == "2024-05-10"
    assert res1["event_provenance"]["event_id"] == "macro-risk-policy-20240510"

    outcomes = res1["outcomes"]
    assert len(outcomes) == 3
    for o in outcomes:
        assert o["status"] == "observed"
        assert o["instrument_kind"] == "index"

    h7 = [o for o in outcomes if o["horizon_sessions"] == 7][0]
    assert h7["exit_session"] == "2024-05-21"
    assert round(h7["forward_return"], 4) == 0.0027

    h28 = [o for o in outcomes if o["horizon_sessions"] == 28][0]
    assert h28["exit_session"] == "2024-06-20"
    assert round(h28["forward_return"], 4) == -0.0445

    # Determinism verification across runs
    res2 = run_rdi_event_horizon_readiness_experiment(
        req,
        event=audited_event,
        horizons=(7, 14, 28),
        root=ROOT,
    )
    assert res1["experiment_hash"] == res2["experiment_hash"]
    assert res1["data_slice_receipt"]["data_hash"] == res2["data_slice_receipt"]["data_hash"]


def test_ri04_consumer2_rdi_event_horizon_blocked_tail_fail_closed() -> None:
    """Consumer 2 Blocked Path: Tail decision (2026-08-20) lacks 14/28 forward bars (#1272)."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000300",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    tail_event = RiskEvent(
        event_id="macro-risk-policy-20260820",
        story_id="story-macro-pboc-2026-tail",
        family="policy_easing",
        direction="policy",
        scope="market",
        sector_id=None,
        stage="announced",
        announced_at=datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 8, 19, 20, 0, tzinfo=timezone.utc),
        active_from=date(2026, 8, 20),
        active_until=date(2026, 9, 30),
        source_id="gov://pbc.gov.cn/notice/2026-0819",
        source_hash="c" * 64,
    )

    res = run_rdi_event_horizon_readiness_experiment(
        req,
        event=tail_event,
        horizons=(7, 14, 28),
        root=ROOT,
    )
    assert res["consumer"] == "ashare_rdi_readiness"
    assert res["status"] == "blocked"
    assert res["experiment_hash"] is None
    assert "Insufficient realized forward sessions" in res["reason"]
    assert "[14, 28]" in res["reason"]

    # Verify tail observations are strictly recorded as insufficient without forward-filling
    outcomes = res["outcomes"]
    h7 = [o for o in outcomes if o["horizon_sessions"] == 7][0]
    assert h7["status"] == "observed"

    h14 = [o for o in outcomes if o["horizon_sessions"] == 14][0]
    assert h14["status"] == "insufficient_future_bars"

    h28 = [o for o in outcomes if o["horizon_sessions"] == 28][0]
    assert h28["status"] == "insufficient_future_bars"


def test_ri04_both_consumers_share_identical_data_slice_receipt() -> None:
    """Proves both distinct consumers bind the exact same underlying slice receipt."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000300",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    c1_res = run_cn_cross_sectional_research_experiment(req, root=ROOT)
    c2_res = run_rdi_event_horizon_readiness_experiment(
        req,
        decision_session="2024-05-10",
        horizons=(7, 14, 28),
        root=ROOT,
    )

    # Identical data slice receipt identity
    assert c1_res["data_slice_receipt"]["slice_id"] == c2_res["data_slice_receipt"]["slice_id"]
    assert c1_res["data_slice_receipt"]["request_hash"] == c2_res["data_slice_receipt"]["request_hash"]
    assert c1_res["data_slice_receipt"]["data_hash"] == c2_res["data_slice_receipt"]["data_hash"]
    assert c1_res["data_slice_receipt"]["source_manifest_hashes"] == c2_res["data_slice_receipt"]["source_manifest_hashes"]


def test_ri04_governance_invariants_and_signal_isolation() -> None:
    """Non-negotiable governance check: research only, zero live trade signals."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001",),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
    )

    c1 = run_cn_cross_sectional_research_experiment(req, root=ROOT)
    c2 = run_rdi_event_horizon_readiness_experiment(req, decision_session="2024-05-10", root=ROOT)

    for res in (c1, c2):
        assert res["research_only"] is True
        assert res["trade_ready"] is False
        assert res["trade_signal"] is False

        # Ensure no operational state leakage
        serialized = json.dumps(res)
        assert "current_weights" not in serialized
        assert "target_weights" not in serialized
        assert "operating_state" not in serialized
