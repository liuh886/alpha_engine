from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.v4_21_state2_intraday_preflight import audit_phase0


def _intraday_frame(symbol: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for session in sessions:
        local = pd.Timestamp(session).tz_localize("America/New_York")
        for minute, scale in (
            ("09:30", 1.0),
            ("10:00", 1.001),
            ("15:30", 1.002),
        ):
            timestamp_et = pd.Timestamp(
                f"{session.date().isoformat()} {minute}",
                tz="America/New_York",
            )
            base = 100.0 + 0.1 * len(rows)
            rows.append(
                {
                    "timestamp_utc": timestamp_et.tz_convert("UTC"),
                    "timestamp_et": timestamp_et,
                    "session_date": local.tz_localize(None).normalize(),
                    "open": base,
                    "high": base * 1.002,
                    "low": base * 0.998,
                    "close": base * scale,
                    "volume": 1000.0,
                    "vwap": base,
                    "transactions": 100.0,
                }
            )
    frame = pd.DataFrame(rows)
    frame.attrs["provider_metadata"] = {
        "pagination_completed": True,
        "provider_symbol": symbol,
    }
    return frame


def _baseline(index: pd.DatetimeIndex, state2_every: int) -> pd.DataFrame:
    state = np.where(np.arange(len(index)) % state2_every == 0, 2, 1)
    frame = pd.DataFrame(index=index)
    frame["position_state"] = state
    frame["weight_QQQI"] = np.where(state == 2, 0.0, 0.5)
    frame["weight_QQQ"] = np.where(state == 2, 0.25, 0.5)
    frame["weight_TQQQ"] = np.where(state == 2, 0.75, 0.0)
    frame["net_return"] = 0.001
    return frame


def _coverage(admissible: list[bool]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["QQQ", "TQQQ", "SPY"],
            "admissible": admissible,
            "pagination_completed": admissible,
            "pages": [2, 2, 2],
        }
    )


def _contract() -> dict:
    return {
        "intraday_data": {
            "symbols": ["QQQ", "TQQQ", "SPY"],
            "end_date": "2025-12-31",
        },
        "phase_0": {
            "development_start": "2020-01-01",
            "development_end": "2022-12-30",
            "quarantine_start": "2023-01-01",
            "minimum_complete_development_years": 3,
            "minimum_development_state2_sessions": 100,
            "minimum_quarantine_state2_sessions": 60,
            "maximum_missing_opening_bar_rate": 0.02,
        },
    }


def test_phase0_passes_with_complete_opening_and_next_open_coverage():
    sessions = pd.bdate_range("2020-01-02", "2025-12-30")
    bars = {
        symbol: _intraday_frame(symbol, sessions)
        for symbol in ("QQQ", "TQQQ", "SPY")
    }
    proxy = _baseline(sessions, state2_every=5)
    actual = _baseline(sessions, state2_every=4)
    result = audit_phase0(
        bars,
        _coverage([True, True, True]),
        proxy,
        actual,
        _contract(),
    )
    assert result.gate["passed"] is True
    assert result.gate["checks"]["complete_pagination"] is True
    assert result.gate["checks"]["state2_weights_match_contract"] is True
    assert result.gate["metrics"]["total_pages"] == 6
    assert set(result.state2_population["sample"]) == {
        "development_proxy",
        "quarantine_actual",
    }


def test_phase0_fails_when_one_source_is_inadmissible():
    sessions = pd.bdate_range("2020-01-02", "2025-12-30")
    bars = {
        symbol: _intraday_frame(symbol, sessions)
        for symbol in ("QQQ", "TQQQ", "SPY")
    }
    result = audit_phase0(
        bars,
        _coverage([True, False, True]),
        _baseline(sessions, 5),
        _baseline(sessions, 4),
        _contract(),
    )
    assert result.gate["passed"] is False
    assert result.gate["checks"]["sources_admissible"] is False
    assert result.gate["checks"]["complete_pagination"] is False


def test_phase0_requires_exact_frozen_state2_weights():
    sessions = pd.bdate_range("2020-01-02", "2025-12-30")
    bars = {
        symbol: _intraday_frame(symbol, sessions)
        for symbol in ("QQQ", "TQQQ", "SPY")
    }
    proxy = _baseline(sessions, 5)
    proxy.loc[proxy["position_state"].eq(2), "weight_QQQ"] = 0.50
    proxy.loc[proxy["position_state"].eq(2), "weight_TQQQ"] = 0.50
    result = audit_phase0(
        bars,
        _coverage([True, True, True]),
        proxy,
        _baseline(sessions, 4),
        _contract(),
    )
    assert result.gate["passed"] is False
    assert result.gate["checks"]["state2_weights_match_contract"] is False
