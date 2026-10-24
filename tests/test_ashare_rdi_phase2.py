"""Synthetic RDI Phase 2: point-in-time, coverage, purge, ETF admission tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.research.ashare_rdi.contracts import RiskEvent
from src.research.ashare_rdi.coverage import FamilyCoverage, audit_coverage, coverage_cells_ready
from src.research.ashare_rdi.outcomes import PriceBar
from src.research.ashare_rdi.phase2 import build_pit_panel, evaluate_blocked_oos, read_price_csv
from src.research.ashare_rdi.phase2_audit import source_readiness
from src.research.ashare_rdi.sector_etfs import SectorETFCandidate, audit_sector_etf


def _cov(day: date, family: str = "holding_change", archived: bool = True) -> FamilyCoverage:
    return FamilyCoverage(day, family, "verified", "fixture://cninfo", "a" * 64, archived)


def _bars(n: int = 240) -> list[PriceBar]:
    d = date(2020, 1, 2)
    return [PriceBar(d + timedelta(days=i), 90 + i % 14, 88 + i % 14, 91 + i % 14) for i in range(n)]


def _event(available: datetime, direction: str = "risk") -> RiskEvent:
    return RiskEvent(
        event_id=f"event-{direction}-{available.day}", story_id="story-1",
        family="holding_change", direction=direction, scope="market", sector_id=None,
        stage="announced", announced_at=available - timedelta(hours=1),
        available_at=available, active_from=date(2020, 3, 1),
        active_until=date(2020, 8, 1), source_id="fixture://cninfo",
        source_hash="a" * 64,
    )


def test_missing_history_never_means_zero_events() -> None:
    a, b = date(2020, 1, 1), date(2020, 1, 2)
    report = audit_coverage([_cov(a)], [a, b], ["holding_change"])
    assert report["status"] == "blocked_incomplete_event_history"
    assert report["missing_cells"] == 1
    assert not coverage_cells_ready({(a, "holding_change"): _cov(a)}, b, ["holding_change"])


def test_unverified_coverage_is_not_eligible() -> None:
    d = date(2020, 1, 2)
    assert audit_coverage([_cov(d, archived=False)], [d], ["holding_change"])["usable_cells"] == 0
    with pytest.raises(ValueError, match="SHA-256"):
        FamilyCoverage(d, "holding_change", "verified", "source", "", True)


def test_pit_panel_filters_future_revisions() -> None:
    bars = _bars()
    coverage = [_cov(p.session) for p in bars]
    first = _event(datetime(2020, 2, 1, tzinfo=timezone.utc))
    later = _event(datetime(2020, 7, 1, tzinfo=timezone.utc), direction="clearing")
    panel, gate = build_pit_panel(
        bars, [first, later], coverage, required_families=["holding_change"],
        horizon=7, validated_sessions=[p.session for p in bars],
    )
    assert gate["history"]["status"] == "ready"
    march = next(r for r in panel if r["session"] == "2020-03-10")
    july = next(r for r in panel if r["session"] == "2020-07-10")
    assert march["risk_density"] == 1.0 and march["clearing_density"] == 0.0
    assert july["risk_density"] == 0.0 and july["clearing_density"] == 1.0


def test_missing_family_blocks_every_research_row() -> None:
    bars = _bars()
    panel, gate = build_pit_panel(
        bars, [], [_cov(p.session) for p in bars],
        required_families=["holding_change", "ipo_refinancing"],
        horizon=14, validated_sessions=[p.session for p in bars],
    )
    assert panel == []
    assert gate["history"]["status"] == "blocked_incomplete_event_history"


def test_provider_calendar_boundary_is_enforced() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="exactly match"):
        build_pit_panel(bars, [], [_cov(p.session) for p in bars],
                        required_families=["holding_change"], horizon=7,
                        validated_sessions=[p.session for p in bars[:-1]])


def test_unobserved_label_tail_is_excluded() -> None:
    bars = _bars(80)
    panel, _ = build_pit_panel(
        bars, [], [_cov(p.session) for p in bars], required_families=["holding_change"],
        horizon=14, validated_sessions=[p.session for p in bars],
    )
    assert len(panel) == 6
    assert panel[-1]["session"] == bars[65].session.isoformat()


def test_oos_purge_removes_overlap_at_actual_label_end() -> None:
    d = date(2018, 1, 1)
    panel = [{
        "session": (d + timedelta(days=i)).isoformat(),
        "end_session": (d + timedelta(days=i + 28)).isoformat(),
        "horizon_sessions": 28,
        "down": int(i % 5 in (0, 1)),
        "risk_density": float((i // 13) % 4),
        "clearing_density": float((i // 19) % 2),
        "bear_drawdown_60": float((i % 17) - 17) / 100,
    } for i in range(330)]
    outcome = evaluate_blocked_oos(panel, horizon=28)
    assert outcome["status"] == "diagnostic_only"
    assert outcome["train_last_label_end"] < outcome["test_first_session"]
    assert outcome["incremental_event_model"]["features"] == [
        "bear_drawdown_60", "risk_density", "clearing_density"
    ]


def test_empty_sample_does_not_report_forecast_skill() -> None:
    assert evaluate_blocked_oos([], horizon=7)["status"] == "insufficient_samples"


def test_pre_inception_ohlcv_excluded_and_rdi_blocked(tmp_path) -> None:
    path = tmp_path / "csi.csv"
    path.write_text(
        "date,open,low,close\n2002-01-04,10,9,10\n"
        "2005-04-08,11,10,11\n2005-04-11,12,11,12\n",
        encoding="utf-8",
    )
    assert [p.session.isoformat() for p in read_price_csv(path)] == ["2005-04-08", "2005-04-11"]
    receipt = source_readiness(path)
    assert receipt["status"] == "blocked_event_pit_coverage"
    assert receipt["last_observed_session"] == "2005-04-11"
    assert receipt["predictive_claim"] is False


def test_sector_etf_eligibility_needs_more_than_ticker_and_inception() -> None:
    etf = SectorETFCandidate(
        "512480.SH", "semiconductors", date(2019, 5, 8), date(2019, 6, 12),
        "https://www.sse.com.cn",
    )
    prices = [
        PriceBar(date(2019, 6, 13) + timedelta(days=i), 2, 1.9, 2.1)
        for i in range(10)
    ]
    report = audit_sector_etf(etf, prices, required_last_session=date(2019, 8, 1))
    assert report["status"] == "blocked"
    assert "liquidity_not_verified" in report["blockers"]
    assert "insufficient_verified_history" in report["blockers"]
