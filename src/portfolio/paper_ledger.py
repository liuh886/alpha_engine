"""Immutable paper-trading ledger (T47.4).

Simulates order submission, fills, slippage, fees, cash, positions,
corporate-action adjustments and daily valuation for an advisory paper
portfolio while preserving explicit links to the ExecutionPlan, ModelVersion,
DataSnapshot and market calendar.

Invariants:

- cash and position accounting reconcile after every event;
- replaying the event chain from genesis reproduces holdings and NAV exactly;
- duplicate submissions are idempotent (same client_order_id never duplicates);
- failed and partial fills are explicit states, never silent drops;
- every record is stamped ``venue=paper_simulation`` / ``live=False`` so a
  simulated event can never be confused with a live brokerage order;
- events form a SHA-256 hash chain; any mutation of persisted history is
  detected by :meth:`PaperTradingLedger.verify`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.execution.models import OrderSide

__all__ = [
    "PaperLedgerError",
    "PaperOrderRequest",
    "SubmissionRecord",
    "FillRecord",
    "BookValuation",
    "ReplayResult",
    "PaperTradingLedger",
]

SCHEMA_VERSION = "paper_ledger_v1"
VENUE = "paper_simulation"
_GENESIS_HASH = "0" * 64


class PaperLedgerError(Exception):
    """Raised when a ledger operation fails closed."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(payload: dict[str, Any], previous_hash: str) -> str:
    material = {"previous_hash": previous_hash, "payload": payload}
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PaperOrderRequest:
    """A simulated order submitted by the operations loop."""

    client_order_id: str
    instrument: str
    side: OrderSide
    quantity: float
    decision_date: str

    def canonical(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "instrument": self.instrument,
            "side": self.side.value,
            "quantity": self.quantity,
            "decision_date": self.decision_date,
        }


@dataclass(frozen=True)
class SubmissionRecord:
    client_order_id: str
    instrument: str
    side: OrderSide
    quantity: float
    decision_date: str
    status: str
    filled_quantity: float
    plan_id: str
    model_version_id: str
    data_snapshot_id: str
    duplicate: bool = False
    venue: str = VENUE
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "venue": self.venue,
            "live": self.live,
            "research_only": True,
            "trade_ready": False,
            "client_order_id": self.client_order_id,
            "instrument": self.instrument,
            "side": self.side.value,
            "quantity": self.quantity,
            "decision_date": self.decision_date,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "plan_id": self.plan_id,
            "model_version_id": self.model_version_id,
            "data_snapshot_id": self.data_snapshot_id,
            "duplicate": self.duplicate,
        }


@dataclass(frozen=True)
class FillRecord:
    client_order_id: str
    trade_date: str
    requested_quantity: float
    filled_quantity: float
    exec_price: float
    reference_price: float
    slippage_cost: float
    fees: float
    cash_delta: float
    status: str
    reason: str = ""
    instrument: str = ""
    side: str = ""
    venue: str = VENUE
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "live": self.live,
            "client_order_id": self.client_order_id,
            "instrument": self.instrument,
            "side": self.side,
            "trade_date": self.trade_date,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "exec_price": self.exec_price,
            "reference_price": self.reference_price,
            "slippage_cost": self.slippage_cost,
            "fees": self.fees,
            "cash_delta": self.cash_delta,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BookValuation:
    trade_date: str
    cash: float
    positions: dict[str, float]
    prices: dict[str, float]
    market_value: float
    nav: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": VENUE,
            "live": False,
            "trade_date": self.trade_date,
            "cash": self.cash,
            "positions": dict(sorted(self.positions.items())),
            "prices": dict(sorted(self.prices.items())),
            "market_value": self.market_value,
            "nav": self.nav,
        }


@dataclass(frozen=True)
class ReplayResult:
    cash: float
    positions: dict[str, float]
    average_costs: dict[str, float]
    nav_series: list[dict[str, Any]]
    event_count: int
    chain_verified: bool


@dataclass
class _OpenOrder:
    request: PaperOrderRequest
    plan_id: str
    model_version_id: str
    data_snapshot_id: str
    filled_quantity: float = 0.0
    status: str = "open"

    @property
    def remaining(self) -> float:
        return self.request.quantity - self.filled_quantity


class PaperTradingLedger:
    """Append-only, hash-chained simulated execution ledger."""

    def __init__(
        self,
        path: str | Path,
        *,
        starting_cash: float,
        slippage_bps: float = 5.0,
        fee_bps: float = 1.0,
    ) -> None:
        reasons: list[str] = []
        if starting_cash <= 0 or not math.isfinite(starting_cash):
            reasons.append("starting_cash must be a positive finite number")
        if slippage_bps < 0 or fee_bps < 0:
            reasons.append("slippage_bps and fee_bps must be non-negative")
        if reasons:
            raise PaperLedgerError(reasons)
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._starting_cash = float(starting_cash)
        self._slippage = slippage_bps / 10_000.0
        self._fee_rate = fee_bps / 10_000.0
        self._events: list[dict[str, Any]] = []
        self._hashes: list[str] = []
        self._open: dict[str, _OpenOrder] = {}
        self._calendar: set[str] = set()
        self._cash = self._starting_cash
        self._positions: dict[str, float] = {}
        self._avg_cost: dict[str, float] = {}
        self._nav_series: list[dict[str, Any]] = []
        if self._path.exists():
            self._load()
        else:
            self._append("genesis", {"starting_cash": self._starting_cash})

    # ------------------------------------------------------------------
    # Event persistence
    # ------------------------------------------------------------------

    def _append(self, event_type: str, payload: dict[str, Any]) -> str:
        stamped = {
            "schema_version": SCHEMA_VERSION,
            "event_type": event_type,
            "venue": VENUE,
            "live": False,
            "research_only": True,
            "trade_ready": False,
            **payload,
        }
        previous = self._hashes[-1] if self._hashes else _GENESIS_HASH
        digest = _digest(stamped, previous)
        line = _canonical_json({"hash": digest, **stamped}) + "\n"
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        self._events.append(stamped)
        self._hashes.append(digest)
        return digest

    def _load(self) -> None:
        result = self.replay()
        if not result.chain_verified:
            raise PaperLedgerError(["persisted ledger hash chain is broken"])
        self._cash = result.cash
        self._positions = dict(result.positions)
        self._avg_cost = dict(result.average_costs)
        self._nav_series = list(result.nav_series)

    # ------------------------------------------------------------------
    # Market calendar
    # ------------------------------------------------------------------

    def set_calendar(self, trading_days: list[str]) -> None:
        self._calendar = set(trading_days)

    def _require_trading_day(self, day: str, purpose: str) -> None:
        if self._calendar and day not in self._calendar:
            raise PaperLedgerError([f"{purpose} date {day} is not in the market calendar"])

    # ------------------------------------------------------------------
    # Orders and fills
    # ------------------------------------------------------------------

    def submit(
        self,
        request: PaperOrderRequest,
        *,
        plan_id: str,
        model_version_id: str,
        data_snapshot_id: str,
    ) -> SubmissionRecord:
        reasons: list[str] = []
        if not request.client_order_id.strip():
            reasons.append("client_order_id is required")
        if not math.isfinite(request.quantity) or request.quantity <= 0:
            reasons.append(f"order quantity must be positive and finite: {request.instrument}")
        if reasons:
            raise PaperLedgerError(reasons)

        existing = self._open.get(request.client_order_id)
        if existing is not None:
            record = self._submission_record(existing)
            return SubmissionRecord(**{**record.__dict__, "duplicate": True})

        open_order = _OpenOrder(
            request=request,
            plan_id=plan_id,
            model_version_id=model_version_id,
            data_snapshot_id=data_snapshot_id,
        )
        self._open[request.client_order_id] = open_order
        self._append(
            "order_submitted",
            {
                **request.canonical(),
                "plan_id": plan_id,
                "model_version_id": model_version_id,
                "data_snapshot_id": data_snapshot_id,
            },
        )
        return self._submission_record(open_order)

    def settle(
        self,
        client_order_id: str,
        *,
        trade_date: str,
        reference_price: float,
        volume: float | None = None,
        max_participation: float | None = None,
        fill_fraction: float | None = None,
        reject_reason: str | None = None,
    ) -> FillRecord:
        order = self._open.get(client_order_id)
        if order is None:
            raise PaperLedgerError([f"unknown or already complete order: {client_order_id}"])
        self._require_trading_day(trade_date, "fill")

        if not math.isfinite(reference_price) or reference_price <= 0:
            raise PaperLedgerError([f"reference price must be positive and finite: {reference_price}"])

        if reject_reason is not None:
            order.status = "rejected"
            self._open.pop(client_order_id, None)
            self._append(
                "order_rejected",
                {"client_order_id": client_order_id, "trade_date": trade_date, "reason": reject_reason},
            )
            return FillRecord(
                client_order_id=client_order_id,
                trade_date=trade_date,
                requested_quantity=order.request.quantity,
                filled_quantity=0.0,
                exec_price=0.0,
                reference_price=reference_price,
                slippage_cost=0.0,
                fees=0.0,
                cash_delta=0.0,
                status="rejected",
                reason=reject_reason,
                instrument=order.request.instrument,
                side=order.request.side.value,
            )

        quantity = order.remaining
        if fill_fraction is not None:
            if not 0.0 < fill_fraction <= 1.0:
                raise PaperLedgerError(["fill_fraction must be within (0, 1]"])
            quantity = min(order.remaining, math.ceil(order.remaining * fill_fraction - 1e-12))
        elif volume is not None and max_participation is not None:
            if volume <= 0 or not 0 < max_participation <= 1.0:
                raise PaperLedgerError(["volume must be positive; max_participation within (0, 1]"])
            quantity = min(quantity, math.floor(volume * max_participation + 1e-9))
        quantity = max(min(quantity, order.remaining), 0.0)

        slip = self._slippage * (1.0 if order.request.side is OrderSide.BUY else -1.0)
        exec_price = reference_price * (1.0 + slip)
        notional = quantity * exec_price
        fees = notional * self._fee_rate
        if order.request.side is OrderSide.BUY:
            cash_delta = -(notional + fees)
            if self._cash + cash_delta < -1e-9:
                order.status = "rejected"
                self._open.pop(client_order_id, None)
                self._append(
                    "order_rejected",
                    {
                        "client_order_id": client_order_id,
                        "trade_date": trade_date,
                        "reason": "insufficient_buying_power",
                    },
                )
                return FillRecord(
                    client_order_id=client_order_id,
                    trade_date=trade_date,
                    requested_quantity=order.request.quantity,
                    filled_quantity=0.0,
                    exec_price=exec_price,
                    reference_price=reference_price,
                    slippage_cost=0.0,
                    fees=0.0,
                    cash_delta=0.0,
                    status="rejected",
                    reason="insufficient_buying_power",
                    instrument=order.request.instrument,
                    side=order.request.side.value,
                )

        if quantity <= 1e-12:
            self._append(
                "order_zero_fill",
                {
                    "client_order_id": client_order_id,
                    "trade_date": trade_date,
                    "reason": "participation cap left no fillable quantity",
                },
            )
            return FillRecord(
                client_order_id=client_order_id,
                trade_date=trade_date,
                requested_quantity=order.request.quantity,
                filled_quantity=0.0,
                exec_price=exec_price,
                reference_price=reference_price,
                slippage_cost=0.0,
                fees=0.0,
                cash_delta=0.0,
                status="zero_fill",
                reason="participation cap left no fillable quantity",
                instrument=order.request.instrument,
                side=order.request.side.value,
            )

        if order.request.side is OrderSide.SELL and quantity > self._positions.get(order.request.instrument, 0.0) + 1e-9:
            order.status = "rejected"
            self._open.pop(client_order_id, None)
            self._append(
                "order_rejected",
                {
                    "client_order_id": client_order_id,
                    "trade_date": trade_date,
                    "reason": "insufficient_position",
                },
            )
            return FillRecord(
                client_order_id=client_order_id,
                trade_date=trade_date,
                requested_quantity=order.request.quantity,
                filled_quantity=0.0,
                exec_price=exec_price,
                reference_price=reference_price,
                slippage_cost=0.0,
                fees=0.0,
                cash_delta=0.0,
                status="rejected",
                reason="insufficient_position",
                instrument=order.request.instrument,
                side=order.request.side.value,
            )

        signed = quantity if order.request.side is OrderSide.BUY else -quantity
        self._apply_fill_to_book(order.request.instrument, signed, exec_price, fees)
        order.filled_quantity += quantity
        order.status = "filled" if order.remaining <= 1e-9 else "partially_filled"
        fully_done = order.status == "filled"
        if fully_done:
            self._open.pop(client_order_id, None)

        slippage_cost = abs(exec_price - reference_price) * quantity
        cash_delta = -signed * exec_price - fees
        self._append(
            "order_filled",
            {
                "client_order_id": client_order_id,
                "instrument": order.request.instrument,
                "side": order.request.side.value,
                "trade_date": trade_date,
                "quantity": signed,
                "exec_price": exec_price,
                "reference_price": reference_price,
                "fees": fees,
                "cash_delta": cash_delta,
                "remaining_after": order.remaining if not fully_done else 0.0,
            },
        )
        return FillRecord(
            client_order_id=client_order_id,
            trade_date=trade_date,
            requested_quantity=order.request.quantity,
            filled_quantity=quantity,
            exec_price=exec_price,
            reference_price=reference_price,
            slippage_cost=slippage_cost,
            fees=fees,
            cash_delta=cash_delta,
            status="filled" if fully_done else "partially_filled",
            instrument=order.request.instrument,
            side=order.request.side.value,
        )

    def _apply_fill_to_book(self, instrument: str, signed_quantity: float, exec_price: float, fees: float) -> None:
        held = self._positions.get(instrument, 0.0)
        cost = self._avg_cost.get(instrument, 0.0)
        if signed_quantity > 0:
            total = held + signed_quantity
            self._avg_cost[instrument] = (held * cost + signed_quantity * exec_price + fees) / total if total else 0.0
            self._positions[instrument] = total
        else:
            sold = min(-signed_quantity, held)
            if sold < held:
                self._positions[instrument] = held - sold
            else:
                self._positions.pop(instrument, None)
                self._avg_cost.pop(instrument, None)
        self._cash += -signed_quantity * exec_price - fees

    def _submission_record(self, order: _OpenOrder) -> SubmissionRecord:
        return SubmissionRecord(
            client_order_id=order.request.client_order_id,
            instrument=order.request.instrument,
            side=order.request.side,
            quantity=order.request.quantity,
            decision_date=order.request.decision_date,
            status=order.status,
            filled_quantity=order.filled_quantity,
            plan_id=order.plan_id,
            model_version_id=order.model_version_id,
            data_snapshot_id=order.data_snapshot_id,
        )

    # ------------------------------------------------------------------
    # Corporate actions and valuation
    # ------------------------------------------------------------------

    def apply_corporate_action(
        self,
        *,
        ex_date: str,
        instrument: str,
        split_ratio: float = 1.0,
        cash_dividend_per_share: float = 0.0,
    ) -> dict[str, Any]:
        self._require_trading_day(ex_date, "corporate-action ex")
        reasons: list[str] = []
        if split_ratio <= 0 or not math.isfinite(split_ratio):
            reasons.append("split_ratio must be positive and finite")
        if cash_dividend_per_share < 0 or not math.isfinite(cash_dividend_per_share):
            reasons.append("cash_dividend_per_share must be non-negative and finite")
        if reasons:
            raise PaperLedgerError(reasons)

        held = self._positions.get(instrument, 0.0)
        dividend_cash = held * cash_dividend_per_share
        new_quantity = held * split_ratio
        if held and split_ratio != 1.0 and self._avg_cost.get(instrument):
            self._avg_cost[instrument] = self._avg_cost[instrument] / split_ratio
        if new_quantity > 0:
            self._positions[instrument] = new_quantity
        elif instrument in self._positions:
            self._positions.pop(instrument)
        self._cash += dividend_cash
        payload = {
            "ex_date": ex_date,
            "instrument": instrument,
            "split_ratio": split_ratio,
            "cash_dividend_per_share": cash_dividend_per_share,
            "quantity_before": held,
            "quantity_after": new_quantity,
            "dividend_cash": dividend_cash,
        }
        self._append("corporate_action", payload)
        return payload

    def mark_book(self, trade_date: str, prices: dict[str, float]) -> BookValuation:
        self._require_trading_day(trade_date, "valuation")
        clean: dict[str, float] = {}
        for instrument, price in prices.items():
            if not math.isfinite(price) or price <= 0:
                raise PaperLedgerError([f"price must be positive and finite: {instrument}={price}"])
            clean[instrument] = price
        market_value = sum(qty * clean[inst] for inst, qty in self._positions.items() if inst in clean)
        missing = sorted(set(self._positions) - set(clean))
        nav = self._cash + market_value
        valuation = BookValuation(
            trade_date=trade_date,
            cash=self._cash,
            positions=dict(self._positions),
            prices=clean,
            market_value=market_value,
            nav=nav,
        )
        self._append(
            "book_valuation",
            {**valuation.to_dict(), "unpriced_positions": missing},
        )
        self._nav_series.append(
            {"trade_date": trade_date, "nav": nav, "cash": self._cash, "market_value": market_value}
        )
        return valuation

    # ------------------------------------------------------------------
    # Replay and verification
    # ------------------------------------------------------------------

    def replay(self) -> ReplayResult:
        events: list[dict[str, Any]] = []
        hashes: list[str] = []
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                digest = raw.pop("hash")
                events.append(raw)
                hashes.append(digest)

        previous = _GENESIS_HASH
        chain_ok = True
        for stored_hash, event in zip(hashes, events):
            expected = _digest(event, previous)
            if expected != stored_hash:
                chain_ok = False
                break
            previous = stored_hash

        genesis_count = sum(1 for e in events if e["event_type"] == "genesis")
        cash = self._starting_cash
        positions: dict[str, float] = {}
        avg_cost: dict[str, float] = {}
        nav_series: list[dict[str, Any]] = []
        if genesis_count == 1 and events and events[0]["event_type"] == "genesis":
            cash = float(events[0]["starting_cash"])
            for event in events[1:]:
                kind = event["event_type"]
                if kind == "order_filled":
                    instrument = event["instrument"]
                    signed = float(event["quantity"]) 
                    price = float(event["exec_price"])
                    fees = float(event["fees"])
                    held = positions.get(instrument, 0.0)
                    cost_basis = avg_cost.get(instrument, 0.0)
                    if signed > 0:
                        total = held + signed
                        avg_cost[instrument] = (
                            (held * cost_basis + signed * price + fees) / total if total else 0.0
                        )
                        positions[instrument] = total
                    else:
                        sold = min(-signed, held)
                        if held - sold > 1e-12:
                            positions[instrument] = held - sold
                        else:
                            positions.pop(instrument, None)
                            avg_cost.pop(instrument, None)
                    cash -= signed * price + fees
                elif kind == "corporate_action":
                    instrument = event["instrument"]
                    ratio = float(event["split_ratio"])
                    dividend = float(event["dividend_cash"])
                    held = positions.get(instrument, 0.0)
                    if held and ratio != 1.0 and avg_cost.get(instrument):
                        avg_cost[instrument] = avg_cost[instrument] / ratio
                    new_quantity = held * ratio
                    if new_quantity > 0:
                        positions[instrument] = new_quantity
                    else:
                        positions.pop(instrument, None)
                    cash += dividend
                elif kind == "book_valuation":
                    nav_series.append(
                        {
                            "trade_date": event["trade_date"],
                            "nav": float(event["nav"]),
                            "cash": float(event["cash"]),
                            "market_value": float(event["market_value"]),
                        }
                    )
        return ReplayResult(
            cash=cash,
            positions=positions,
            average_costs=avg_cost,
            nav_series=nav_series,
            event_count=len(events),
            chain_verified=chain_ok and bool(events) and events[0]["event_type"] == "genesis",
        )

    def verify(self) -> None:
        result = self.replay()
        reasons: list[str] = []
        if not result.chain_verified:
            reasons.append("persisted ledger hash chain is broken")
        if not math.isclose(result.cash, self._cash, abs_tol=1e-6):
            reasons.append(f"replayed cash {result.cash:.6f} diverges from book {self._cash:.6f}")
        for instrument, quantity in self._positions.items():
            replayed = result.positions.get(instrument)
            if replayed is None or not math.isclose(replayed, quantity, abs_tol=1e-9):
                reasons.append(f"replayed position for {instrument} diverges from book")
        for instrument in set(result.positions) - set(self._positions):
            reasons.append(f"replay holds unexpected position: {instrument}")
        if len(result.nav_series) != len(self._nav_series):
            reasons.append("replayed valuation count diverges from book history")
        else:
            for stored, replayed in zip(self._nav_series, result.nav_series):
                if not math.isclose(stored["nav"], replayed["nav"], abs_tol=1e-6):
                    reasons.append(
                        f"replayed NAV on {stored['trade_date']} diverges from stored valuation"
                    )
                    break
        if reasons:
            raise PaperLedgerError(reasons)

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    @property
    def nav_history(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._nav_series]
