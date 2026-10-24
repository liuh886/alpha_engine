"""Synthetic contract tests; no market-data or trading claims."""

from datetime import date, datetime, timedelta, timezone

import pytest

from src.research.ashare_rdi import PriceBar, RiskEvent, event_exposure_timeline, forward_outcomes


UTC = timezone.utc
DAY = date(2026, 10, 21)
CUTOFF = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)


def _event(**overrides: object) -> RiskEvent:
    payload: dict[str, object] = {
        "event_id": "v1",
        "story_id": "one-development",
        "family": "holding_change",
        "direction": "risk",
        "scope": "market",
        "sector_id": None,
        "stage": "announced",
        "announced_at": datetime(2026, 10, 20, 8, tzinfo=UTC),
        "available_at": datetime(2026, 10, 20, 9, tzinfo=UTC),
        "active_from": date(2026, 10, 22),
        "active_until": date(2026, 10, 28),
        "source_id": "fixture://disclosure",
        "source_hash": "fixture-hash",
    }
    payload.update(overrides)
    return RiskEvent(**payload)  # type: ignore[arg-type]


def test_pit_future_revisions_do_not_leak() -> None:
    first = _event()
    future_revision = _event(
        event_id="v2", stage="verified",
        announced_at=datetime(2026, 10, 22, 8, tzinfo=UTC),
        available_at=datetime(2026, 10, 22, 9, tzinfo=UTC),
        direction="clearing",
    )
    scores = event_exposure_timeline(
        [first, future_revision], as_of=CUTOFF, future_sessions=[date(2026, 10, 22)]
    )
    assert scores[0]["risk_stories"] == 1
    assert scores[0]["clearing_stories"] == 0


def test_multiple_articles_about_one_story_count_once() -> None:
    a = _event(event_id="source1")
    b = _event(event_id="source2", source_id="fixture://second", available_at=CUTOFF)
    rows = event_exposure_timeline(
        [a, b], as_of=CUTOFF, future_sessions=[date(2026, 10, 22)]
    )
    assert rows[0]["risk_stories"] == 1


def test_sector_events_cannot_contaminate_other_sectors() -> None:
    event = _event(scope="sector", sector_id="electronics")
    dates = [date(2026, 10, 22)]
    assert event_exposure_timeline([event], as_of=CUTOFF, future_sessions=dates)[0]["risk_stories"] == 0
    assert event_exposure_timeline(
        [event], as_of=CUTOFF, future_sessions=dates, sector_id="electronics"
    )[0]["risk_stories"] == 1


def test_timezones_and_effective_window_validated() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _event(available_at=datetime(2026, 10, 20, 9))
    with pytest.raises(ValueError, match="window"):
        _event(active_from=date(2026, 10, 30))


def _bars() -> list[PriceBar]:
    return [
        PriceBar(DAY + timedelta(days=i), 100.0 + i, 99.0 + i, 100.5 + i)
        for i in range(31)
    ]


def test_index_horizon_is_t_plus_h_and_no_trade_claim() -> None:
    bars = _bars()
    outcomes = forward_outcomes(bars, decision_session=DAY, horizons=(7,), instrument_kind="index")
    assert outcomes[0]["exit_session"] == bars[7].session.isoformat()
    assert outcomes[0]["entry_session"] == DAY.isoformat()
    assert outcomes[0]["forward_return"] == pytest.approx(bars[7].close / bars[0].close - 1)


def test_etf_entry_is_next_open() -> None:
    bars = _bars()
    outcomes = forward_outcomes(bars, decision_session=DAY, horizons=(7,), instrument_kind="etf")
    assert outcomes[0]["entry_session"] == bars[1].session.isoformat()
    assert outcomes[0]["forward_return"] == pytest.approx(bars[7].close / bars[1].open - 1)


def test_incomplete_forward_window_is_explicit() -> None:
    rows = forward_outcomes(_bars()[:8], decision_session=DAY)
    assert [r["status"] for r in rows] == [
        "observed", "insufficient_future_bars", "insufficient_future_bars"
    ]


def test_reject_duplicate_sessions_and_bad_lookahead_windows() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="unique"):
        forward_outcomes([bars[0], bars[0]], decision_session=DAY)
    with pytest.raises(ValueError, match="future_sessions"):
        event_exposure_timeline([_event()], as_of=CUTOFF, future_sessions=[DAY])
