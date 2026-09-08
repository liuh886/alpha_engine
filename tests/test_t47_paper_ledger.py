"""T47.4: Immutable paper-trading ledger tests.

Verify:
- cash/position accounting reconciles on every event and replay reproduces it
- duplicate submissions are idempotent
- failed/partial fills are explicit states
- corporate actions preserve value and adjust cost basis
- simulated records can never be confused with live brokerage orders
- the hash chain detects any mutation of persisted history
"""

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.execution.models import OrderSide
from src.portfolio.paper_ledger import (
    BookValuation,
    FillRecord,
    PaperLedgerError,
    PaperOrderRequest,
    PaperTradingLedger,
    ReplayResult,
    SubmissionRecord,
)

CALENDAR = ["2026-08-24", "2026-08-25", "2026-08-26"]
START_CASH = 100_000.0


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "paper_ledger.jsonl"


@pytest.fixture
def ledger(ledger_path):
    ledger = PaperTradingLedger(
        ledger_path,
        starting_cash=START_CASH,
        slippage_bps=10.0,
        fee_bps=5.0,
    )
    ledger.set_calendar(CALENDAR)
    return ledger


def buy(ledger, qty, ref, cid="o-buy-1", date="2026-08-24"):
    request = PaperOrderRequest(
        client_order_id=cid,
        instrument="AAA",
        side=OrderSide.BUY,
        quantity=qty,
        decision_date=date,
    )
    submission = ledger.submit(
        request,
        plan_id="plan_1",
        model_version_id="mv_1",
        data_snapshot_id="snap_1",
    )
    return submission, ledger.settle(cid, trade_date=date, reference_price=ref)


# ---------------------------------------------------------------------------
# Boundary stamping and genesis
# ---------------------------------------------------------------------------


def test_genesis_event_and_boundary_stamping(ledger):
    result = ledger.replay()
    assert result.chain_verified
    assert result.event_count == 1


def test_records_can_never_look_like_live_brokerage_events(ledger):
    submission, _ = buy(ledger, 10, 100.0)
    payload = submission.to_dict()
    assert payload["venue"] == "paper_simulation"
    assert payload["live"] is False
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    for event in [json.loads(line) for line in ledger._path.read_text(encoding="utf-8").splitlines()]:
        assert event["venue"] == "paper_simulation"
        assert event["live"] is False


def test_submission_preserves_execution_plan_and_model_identity(ledger):
    submission, _ = buy(ledger, 10, 100.0)
    assert submission.plan_id == "plan_1"
    assert submission.model_version_id == "mv_1"
    assert submission.data_snapshot_id == "snap_1"


# ---------------------------------------------------------------------------
# Fills and accounting
# ---------------------------------------------------------------------------


def test_buy_fill_updates_cash_position_and_average_cost(ledger):
    _, fill = buy(ledger, 10, 100.0)
    expected_exec = 100.0 * (1.0 + 0.0010)
    expected_fee = 10 * expected_exec * 0.0005
    assert isinstance(fill, FillRecord)
    assert fill.status == "filled"
    assert math.isclose(fill.exec_price, expected_exec, abs_tol=1e-9)
    assert math.isclose(ledger.cash, START_CASH - 10 * expected_exec - expected_fee, abs_tol=1e-6)
    assert ledger.positions == {"AAA": 10.0}
    ledger.verify()


def test_round_trip_costs_are_symmetric_slippage_plus_fees(ledger):
    start = ledger.cash
    buy(ledger, 10, 100.0, cid="b1")
    request = PaperOrderRequest("s1", "AAA", OrderSide.SELL, 10.0, "2026-08-25")
    ledger.submit(request, plan_id="plan_1", model_version_id="mv_1", data_snapshot_id="snap_1")
    fill = ledger.settle("s1", trade_date="2026-08-25", reference_price=100.0)
    assert fill.exec_price < 100.0
    assert ledger.positions == {}
    assert math.isclose(ledger.cash, start - 3.0, abs_tol=1e-6)
    ledger.verify()


def submit_only(ledger, cid, qty, instrument="AAA", side=OrderSide.BUY, date="2026-08-24"):
    request = PaperOrderRequest(cid, instrument, side, qty, date)
    return ledger.submit(request, plan_id="plan_1", model_version_id="mv_1", data_snapshot_id="snap_1")


def test_partial_fill_is_explicit_and_resumable(ledger):
    submission = submit_only(ledger, "o-buy-1", 100.0)
    first = ledger.settle("o-buy-1", trade_date="2026-08-24", reference_price=50.0, fill_fraction=0.4)
    assert isinstance(first, FillRecord)
    assert math.isclose(first.filled_quantity, 40.0, abs_tol=1e-9)
    partial = ledger.settle("o-buy-1", trade_date="2026-08-25", reference_price=50.0, fill_fraction=0.4)
    assert partial.status == "partially_filled"
    assert math.isclose(partial.filled_quantity, 24.0, abs_tol=1e-9)
    duplicate = ledger.submit(
        PaperOrderRequest("o-buy-1", "AAA", OrderSide.BUY, 100.0, "2026-08-24"),
        plan_id="plan_1",
        model_version_id="mv_1",
        data_snapshot_id="snap_1",
    )
    assert duplicate.duplicate is True
    assert math.isclose(duplicate.filled_quantity, 64.0, abs_tol=1e-9)
    assert submission.status == "open"
    final = ledger.settle("o-buy-1", trade_date="2026-08-26", reference_price=50.0, fill_fraction=1.0)
    assert final.status == "filled"
    assert math.isclose(final.filled_quantity, 36.0, abs_tol=1e-9)
    assert math.isclose(ledger.positions["AAA"], 100.0, abs_tol=1e-9)
    with pytest.raises(PaperLedgerError):
        ledger.settle("o-buy-1", trade_date="2026-08-26", reference_price=50.0)
    ledger.verify()


def test_participation_cap_zero_fill_is_persisted(ledger):
    submit_only(ledger, "o-buy-1", 100.0)
    zero = ledger.settle(
        "o-buy-1",
        trade_date="2026-08-24",
        reference_price=50.0,
        volume=1.0,
        max_participation=0.01,
    )
    assert zero.status == "zero_fill"
    kinds = [
        json.loads(line)["event_type"]
        for line in ledger._path.read_text(encoding="utf-8").splitlines()
    ]
    assert "order_zero_fill" in kinds
    ledger.verify()


def test_insufficient_buying_power_rejects_without_state_change(ledger):
    poor = PaperTradingLedger(ledger._path.parent / "poor.jsonl", starting_cash=100.0)
    request = PaperOrderRequest("big", "AAA", OrderSide.BUY, 100.0, "2026-08-24")
    poor.submit(request, plan_id="p", model_version_id="m", data_snapshot_id="s")
    fill = poor.settle("big", trade_date="2026-08-24", reference_price=50.0)
    assert fill.status == "rejected"
    assert fill.reason == "insufficient_buying_power"
    assert poor.cash == 100.0
    assert poor.positions == {}


def test_oversell_is_rejected_explicitly(ledger):
    request = PaperOrderRequest("short", "AAA", OrderSide.SELL, 10.0, "2026-08-24")
    ledger.submit(request, plan_id="p", model_version_id="m", data_snapshot_id="s")
    fill = ledger.settle("short", trade_date="2026-08-24", reference_price=50.0)
    assert fill.status == "rejected"
    assert fill.reason == "insufficient_position"
    assert ledger.cash == START_CASH


def test_duplicate_submission_never_appends_a_second_order_event(ledger):
    request = PaperOrderRequest("dup", "AAA", OrderSide.BUY, 10.0, "2026-08-24")
    first = ledger.submit(request, plan_id="p", model_version_id="m", data_snapshot_id="s")
    count_after_first = ledger.replay().event_count
    second = ledger.submit(request, plan_id="p", model_version_id="m", data_snapshot_id="s")
    assert ledger.replay().event_count == count_after_first
    assert first.duplicate is False
    assert second.duplicate is True


def test_unknown_order_settlement_fails_closed(ledger):
    with pytest.raises(PaperLedgerError):
        ledger.settle("ghost", trade_date="2026-08-24", reference_price=10.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"volume": -5.0, "max_participation": 0.1},
        {"volume": 100.0, "max_participation": 0.0},
        {"fill_fraction": 0.0},
        {"fill_fraction": 1.5},
    ],
)
def test_invalid_settlement_parameters_fail_closed(ledger, kwargs):
    submit_only(ledger, f"o-{id(kwargs)}", 10.0)
    with pytest.raises(PaperLedgerError):
        ledger.settle(
            f"o-{id(kwargs)}", trade_date="2026-08-25", reference_price=50.0, **kwargs
        )


# ---------------------------------------------------------------------------
# Corporate actions and valuation
# ---------------------------------------------------------------------------


def test_split_adjusts_quantity_and_cost_basis_preserving_value(ledger):
    buy(ledger, 100, 50.0)
    before = ledger.mark_book("2026-08-24", {"AAA": 50.0})
    payload = ledger.apply_corporate_action(ex_date="2026-08-25", instrument="AAA", split_ratio=2.0)
    assert math.isclose(payload["quantity_after"], 200.0, abs_tol=1e-9)
    after = ledger.mark_book("2026-08-25", {"AAA": 25.0})
    assert math.isclose(after.nav, before.nav, rel_tol=1e-9)
    ledger.verify()


def test_cash_dividend_credits_cash_exactly(ledger):
    buy(ledger, 100, 50.0)
    cash_before = ledger.cash
    payload = ledger.apply_corporate_action(
        ex_date="2026-08-25", instrument="AAA", cash_dividend_per_share=0.5
    )
    assert math.isclose(payload["dividend_cash"], 50.0, abs_tol=1e-9)
    assert math.isclose(ledger.cash, cash_before + 50.0, abs_tol=1e-9)
    ledger.verify()


def test_corporate_action_validation_fails_closed(ledger):
    with pytest.raises(PaperLedgerError):
        ledger.apply_corporate_action(ex_date="2026-08-25", instrument="AAA", split_ratio=-1.0)
    with pytest.raises(PaperLedgerError):
        ledger.apply_corporate_action(
            ex_date="2026-08-25", instrument="AAA", cash_dividend_per_share=-0.5
        )


def test_market_calendar_gates_fills_and_valuations(ledger):
    submit_only(ledger, "cal-1", 10.0)
    with pytest.raises(PaperLedgerError):
        ledger.settle("cal-1", trade_date="2026-08-30", reference_price=50.0)
    buy(ledger, 10, 50.0, cid="cal-2")
    with pytest.raises(PaperLedgerError):
        ledger.mark_book("2026-12-25", {"AAA": 50.0})


def test_nav_reconciles_with_cash_and_positions():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ledger = PaperTradingLedger(Path(tmp) / "l.jsonl", starting_cash=10_000.0)
        ledger.set_calendar(["2026-08-24"])
        request = PaperOrderRequest("x", "BBB", OrderSide.BUY, 3.0, "2026-08-24")
        ledger.submit(request, plan_id="p", model_version_id="m", data_snapshot_id="s")
        ledger.settle("x", trade_date="2026-08-24", reference_price=100.0)
        valuation = ledger.mark_book("2026-08-24", {"BBB": 101.0})
        assert isinstance(valuation, BookValuation)
        expected = valuation.cash + 3.0 * 101.0
        assert math.isclose(valuation.nav, expected, abs_tol=1e-9)


def test_unpriced_positions_are_disclosed_not_hidden(ledger):
    buy(ledger, 10, 50.0)
    valuation = ledger.mark_book("2026-08-25", {})
    assert valuation.market_value == 0.0
    stored = [json.loads(line) for line in ledger._path.read_text(encoding="utf-8").splitlines()]
    valuations = [e for e in stored if e["event_type"] == "book_valuation"]
    assert valuations[-1]["unpriced_positions"] == ["AAA"]


# ---------------------------------------------------------------------------
# Replay, reload and tamper evidence
# ---------------------------------------------------------------------------


def test_reload_from_disk_reproduces_exact_book_state(ledger):
    buy(ledger, 10, 100.0)
    ledger.mark_book("2026-08-24", {"AAA": 101.0})
    ledger.apply_corporate_action(ex_date="2026-08-25", instrument="AAA", cash_dividend_per_share=0.25)
    expected_cash = ledger.cash
    expected_positions = ledger.positions
    expected_nav = ledger.nav_history

    reopened = PaperTradingLedger(ledger._path, starting_cash=START_CASH)
    assert math.isclose(reopened.cash, expected_cash, abs_tol=1e-6)
    assert reopened.positions.keys() == expected_positions.keys()
    assert math.isclose(reopened.positions["AAA"], expected_positions["AAA"], abs_tol=1e-9)
    assert reopened.nav_history == expected_nav
    reopened.verify()


def test_full_sequence_replays_to_identical_nav_series(ledger):
    buy(ledger, 20, 100.0)
    ledger.mark_book("2026-08-24", {"AAA": 102.0})
    submit_only(ledger, "add-1", 10.0, date="2026-08-25")
    ledger.settle("add-1", trade_date="2026-08-25", reference_price=103.0, fill_fraction=0.5)
    ledger.mark_book("2026-08-25", {"AAA": 104.0})
    result: ReplayResult = ledger.replay()
    assert result.chain_verified
    assert len(result.nav_series) == len(ledger.nav_history)
    for stored, replayed in zip(ledger.nav_history, result.nav_series):
        assert stored == replayed


def test_hash_chain_detects_history_mutation(ledger):
    buy(ledger, 10, 100.0)
    path = ledger._path
    lines = path.read_text(encoding="utf-8").splitlines()
    mutated = json.loads(lines[1])
    mutated["quantity"] = mutated["quantity"] + 1.0
    lines[1] = json.dumps(mutated, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(PaperLedgerError) as excinfo:
        PaperTradingLedger(path, starting_cash=START_CASH)
    assert any("hash chain" in r for r in excinfo.value.reasons)


def test_constructor_validation_fails_closed(ledger_path, tmp_path):
    with pytest.raises(PaperLedgerError):
        PaperTradingLedger(tmp_path / "a.jsonl", starting_cash=0.0)
    with pytest.raises(PaperLedgerError):
        PaperTradingLedger(tmp_path / "b.jsonl", starting_cash=1_000.0, slippage_bps=-1.0)
    with pytest.raises(PaperLedgerError):
        PaperTradingLedger(tmp_path / "c.jsonl", starting_cash=float("nan"))


def test_invalid_submissions_fail_closed(ledger):
    for bad in (
        PaperOrderRequest("", "AAA", OrderSide.BUY, 10.0, "2026-08-24"),
        PaperOrderRequest("neg", "AAA", OrderSide.BUY, -1.0, "2026-08-24"),
        PaperOrderRequest("nan", "AAA", OrderSide.BUY, float("nan"), "2026-08-24"),
    ):
        with pytest.raises(PaperLedgerError):
            ledger.submit(bad, plan_id="p", model_version_id="m", data_snapshot_id="s")


def test_nonpositive_prices_fail_closed(ledger):
    submit_only(ledger, "px-1", 10.0)
    with pytest.raises(PaperLedgerError):
        ledger.settle("px-1", trade_date="2026-08-24", reference_price=0.0)
    buy(ledger, 10, 50.0, cid="px-2")
    with pytest.raises(PaperLedgerError):
        ledger.mark_book("2026-08-26", {"BAD": -3.0})
