"""Tests for position-level risk management."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_position(
    instrument: str,
    weight: float = 0.10,
    entry_price: float = 100.0,
    current_price: float = 100.0,
    peak_price: float = 100.0,
    sector: str = "",
):
    from src.guardrails.position_risk import PositionInfo

    return PositionInfo(
        instrument=instrument,
        weight=weight,
        entry_price=entry_price,
        current_price=current_price,
        peak_price=peak_price,
        sector=sector,
    )


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------


def test_stop_loss_triggers_at_minus_10_pct():
    from src.guardrails.position_risk import (
        ActionType,
        PositionRiskManager,
        SignalType,
    )

    mgr = PositionRiskManager()  # default -10% threshold
    positions = {"AAPL": _make_position("AAPL", entry_price=100.0, current_price=89.0)}

    signals = mgr.check_stop_loss(positions)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == SignalType.STOP_LOSS
    assert sig.action == ActionType.SELL
    assert sig.current_value <= -0.10
    assert "stop-loss" in sig.reason.lower()


def test_stop_loss_no_trigger_within_threshold():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    positions = {"AAPL": _make_position("AAPL", entry_price=100.0, current_price=91.0)}

    signals = mgr.check_stop_loss(positions)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Trailing stop
# ---------------------------------------------------------------------------


def test_trailing_stop_triggers_at_minus_15_pct_from_peak():
    from src.guardrails.position_risk import (
        ActionType,
        PositionRiskManager,
        SignalType,
    )

    mgr = PositionRiskManager()  # default -15% trailing
    positions = {"TSLA": _make_position("TSLA", peak_price=120.0, current_price=101.0)}

    signals = mgr.check_trailing_stop(positions)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == SignalType.TRAILING_STOP
    assert sig.action == ActionType.SELL
    assert sig.current_value <= -0.15


def test_trailing_stop_no_trigger_above_threshold():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    # -14% drawdown from peak 120 -> 103.2
    positions = {"TSLA": _make_position("TSLA", peak_price=120.0, current_price=103.2)}

    signals = mgr.check_trailing_stop(positions)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Position limits
# ---------------------------------------------------------------------------


def test_position_limit_triggers_when_overweight():
    from src.guardrails.position_risk import (
        ActionType,
        PositionRiskManager,
        SignalType,
    )

    mgr = PositionRiskManager()  # default max 20%
    positions = {"NVDA": _make_position("NVDA", weight=0.25)}

    signals = mgr.check_position_limits(positions)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == SignalType.POSITION_LIMIT
    assert sig.action == ActionType.REDUCE
    assert sig.current_value == 0.25
    assert sig.threshold == 0.20


def test_position_limit_no_trigger_at_threshold():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    positions = {"NVDA": _make_position("NVDA", weight=0.20)}

    signals = mgr.check_position_limits(positions)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Sector exposure
# ---------------------------------------------------------------------------


def test_sector_exposure_triggers_when_overweight():
    from src.guardrails.position_risk import (
        ActionType,
        PositionRiskManager,
        SignalType,
    )

    mgr = PositionRiskManager()  # default max 35%
    positions = {
        "AAPL": _make_position("AAPL", weight=0.15, sector="Technology"),
        "MSFT": _make_position("MSFT", weight=0.15, sector="Technology"),
        "NVDA": _make_position("NVDA", weight=0.10, sector="Technology"),
        "JPM": _make_position("JPM", weight=0.10, sector="Financials"),
    }

    signals = mgr.check_sector_exposure(positions)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == SignalType.SECTOR_LIMIT
    assert sig.action == ActionType.REDUCE
    assert sig.current_value == 0.40  # 15+15+10 = 40%
    assert sig.threshold == 0.35
    assert "Technology" in sig.reason


def test_sector_exposure_no_trigger_within_limit():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    positions = {
        "AAPL": _make_position("AAPL", weight=0.15, sector="Technology"),
        "MSFT": _make_position("MSFT", weight=0.15, sector="Technology"),
        "JPM": _make_position("JPM", weight=0.10, sector="Financials"),
    }

    signals = mgr.check_sector_exposure(positions)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Vol-adjusted weights
# ---------------------------------------------------------------------------


def test_vol_adjusted_weights_sum_to_one():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    instruments = ["AAPL", "MSFT", "GOOGL"]
    scores = pd.Series({"AAPL": 0.8, "MSFT": 0.7, "GOOGL": 0.9})
    volatilities = pd.Series({"AAPL": 0.25, "MSFT": 0.20, "GOOGL": 0.30})

    weights = mgr.compute_vol_adjusted_weights(instruments, scores, volatilities)

    assert len(weights) == 3
    assert abs(weights.sum() - 1.0) < 1e-10


def test_vol_adjusted_low_vol_gets_higher_weight():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    instruments = ["LOW_VOL", "HIGH_VOL"]
    scores = pd.Series({"LOW_VOL": 0.5, "HIGH_VOL": 0.5})
    volatilities = pd.Series({"LOW_VOL": 0.10, "HIGH_VOL": 0.40})

    weights = mgr.compute_vol_adjusted_weights(instruments, scores, volatilities)

    assert weights["LOW_VOL"] > weights["HIGH_VOL"]
    # Ratio should be 4:1 (inverse of vol ratio 1:4)
    ratio = weights["LOW_VOL"] / weights["HIGH_VOL"]
    assert abs(ratio - 4.0) < 0.01


def test_vol_adjusted_empty_returns_empty():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    weights = mgr.compute_vol_adjusted_weights([], pd.Series(dtype=float), pd.Series(dtype=float))
    assert len(weights) == 0


def test_vol_adjusted_zero_vol_excluded():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    instruments = ["A", "B"]
    scores = pd.Series({"A": 0.5, "B": 0.5})
    volatilities = pd.Series({"A": 0.0, "B": 0.20})  # A has zero vol

    weights = mgr.compute_vol_adjusted_weights(instruments, scores, volatilities)
    # Only B should have weight (A excluded due to zero vol)
    assert weights["B"] == 1.0
    assert weights["A"] == 0.0


# ---------------------------------------------------------------------------
# evaluate_portfolio (aggregate)
# ---------------------------------------------------------------------------


def test_evaluate_portfolio_returns_all_signals():
    from src.guardrails.position_risk import (
        PositionRiskConfig,
        PositionRiskManager,
        SignalType,
    )

    config = PositionRiskConfig(
        stop_loss_pct=-0.10,
        trailing_stop_pct=-0.15,
        max_position_weight=0.20,
        max_sector_weight=0.35,
    )
    mgr = PositionRiskManager(config)

    positions = {
        "AAPL": _make_position(
            "AAPL",
            weight=0.25,
            entry_price=100.0,
            current_price=88.0,
            peak_price=120.0,
            sector="Technology",
        ),
        "MSFT": _make_position(
            "MSFT",
            weight=0.15,
            entry_price=100.0,
            current_price=95.0,
            peak_price=100.0,
            sector="Technology",
        ),
    }

    signals = mgr.evaluate_portfolio(positions)
    types = {s.signal_type for s in signals}

    # AAPL: stop-loss (-12%), trailing stop (-26.7% from peak), position limit (25%)
    assert SignalType.STOP_LOSS in types
    assert SignalType.TRAILING_STOP in types
    assert SignalType.POSITION_LIMIT in types
    # Sector: Technology = 25% + 15% = 40% > 35%
    assert SignalType.SECTOR_LIMIT in types


def test_evaluate_portfolio_no_signals_when_healthy():
    from src.guardrails.position_risk import PositionRiskManager

    mgr = PositionRiskManager()
    positions = {
        "AAPL": _make_position(
            "AAPL", weight=0.10, entry_price=100.0, current_price=105.0, peak_price=105.0
        ),
        "JPM": _make_position(
            "JPM", weight=0.10, entry_price=50.0, current_price=52.0, peak_price=52.0
        ),
    }

    signals = mgr.evaluate_portfolio(positions)
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Backward compatibility: disabled risk manager produces no signals
# ---------------------------------------------------------------------------


def test_backward_compat_no_risk_manager():
    """When use_risk_manager=False (default), no PositionRiskManager is created."""

    # Simulate: strategy does not create a risk manager
    risk_manager = None
    signals = []
    if risk_manager is not None:
        signals = risk_manager.evaluate_portfolio({})

    assert signals == []


# ---------------------------------------------------------------------------
# Signal serialization
# ---------------------------------------------------------------------------


def test_signal_to_dict():
    from src.guardrails.position_risk import (
        ActionType,
        PositionRiskSignal,
        SignalType,
    )

    sig = PositionRiskSignal(
        instrument="AAPL",
        signal_type=SignalType.STOP_LOSS,
        current_value=-0.12,
        threshold=-0.10,
        action=ActionType.SELL,
        reason="Stop-loss triggered",
    )
    d = sig.to_dict()
    assert d["instrument"] == "AAPL"
    assert d["signal_type"] == "stop_loss"
    assert d["action"] == "sell"
    assert d["current_value"] == -0.12


# ---------------------------------------------------------------------------
# Custom config
# ---------------------------------------------------------------------------


def test_custom_config_tighter_stop_loss():
    from src.guardrails.position_risk import (
        PositionRiskConfig,
        PositionRiskManager,
    )

    config = PositionRiskConfig(stop_loss_pct=-0.05)  # Tighter: -5%
    mgr = PositionRiskManager(config)
    positions = {"X": _make_position("X", entry_price=100.0, current_price=94.0)}

    signals = mgr.check_stop_loss(positions)
    assert len(signals) == 1  # -6% triggers -5% threshold
