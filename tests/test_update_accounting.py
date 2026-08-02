"""Truthful data-update accounting contracts."""

from __future__ import annotations

import pytest

from src.data.update_accounting import (
    DataUpdateFailure,
    FailureReason,
    UpdateAccountingReport,
    create_accounting_report,
)


def _make_report(
    *,
    cn_symbols: list[str] | None = None,
    us_symbols: list[str] | None = None,
) -> UpdateAccountingReport:
    configured: dict[str, list[str]] = {}
    if cn_symbols is not None:
        configured["cn"] = cn_symbols
    if us_symbols is not None:
        configured["us"] = us_symbols
    return UpdateAccountingReport(configured=configured)


def test_complete_report_is_complete():
    report = _make_report(
        cn_symbols=["SH600000", "SZ000001"],
        us_symbols=["AAPL", "MSFT"],
    )
    for market, symbols in report.configured.items():
        for symbol in symbols:
            report.add("updated", market, symbol)
    assert report.is_complete is True


def test_mixed_terminal_states_are_fully_accounted():
    report = _make_report(cn_symbols=["A", "B", "C", "D", "E"])
    report.add("updated", "cn", "A")
    report.add("reused", "cn", "B")
    report.add("excluded", "cn", "C", reason=FailureReason.EXCLUDED_BY_POLICY)
    report.add("failed", "cn", "D", reason=FailureReason.FETCH_FAILED)
    report.add("stale", "cn", "E", reason=FailureReason.STALE_DATA)
    assert report.is_complete is True


def test_missing_or_unattempted_symbols_are_incomplete():
    report = _make_report(us_symbols=["AAPL", "GOOG"])
    report.add("attempted", "us", "AAPL")
    report.add("updated", "us", "AAPL")
    assert report.is_complete is False


def test_empty_configuration_is_vacuously_complete():
    assert UpdateAccountingReport(configured={}).is_complete is True


def test_failure_reason_enum_is_stable():
    expected = {
        "FETCH_FAILED",
        "VALIDATION_FAILED",
        "STALE_DATA",
        "PROVIDER_ERROR",
        "EXCLUDED_BY_POLICY",
        "SCHEMA_MISMATCH",
        "CONSISTENCY_CHECK_FAILED",
        "UNKNOWN",
    }
    assert {member.name for member in FailureReason} == expected
    assert all(member.value == member.name for member in FailureReason)


@pytest.mark.parametrize("reason", list(FailureReason))
def test_every_failure_reason_can_be_recorded(reason: FailureReason):
    report = _make_report(us_symbols=["AAPL"])
    report.add("failed", "us", "AAPL", reason=reason)
    assert report.reasons["failed"]["us:AAPL"] == reason.value


def test_summary_contains_required_evidence_fields():
    report = _make_report(cn_symbols=["SH600000"], us_symbols=["AAPL"])
    report.add("updated", "cn", "SH600000")
    report.add("updated", "us", "AAPL")

    summary = report.summary_dict()

    for key in (
        "is_complete",
        "total_configured",
        "total_updated",
        "total_reused",
        "total_excluded",
        "total_failed",
        "total_stale",
        "markets",
        "reasons",
    ):
        assert key in summary
    for market in ("cn", "us"):
        for field in (
            "configured",
            "attempted",
            "updated",
            "reused",
            "excluded",
            "failed",
            "stale",
        ):
            assert field in summary["markets"][market]


def test_summary_counts_and_reasons_are_truthful():
    report = _make_report(us_symbols=["AAPL", "GOOG", "MSFT"])
    report.add("updated", "us", "AAPL")
    report.add("failed", "us", "GOOG", reason=FailureReason.FETCH_FAILED)
    report.add("stale", "us", "MSFT", reason=FailureReason.STALE_DATA)

    summary = report.summary_dict()

    assert summary["total_configured"] == 3
    assert summary["total_updated"] == 1
    assert summary["total_failed"] == 1
    assert summary["total_stale"] == 1
    assert summary["reasons"]["failed"]["us:GOOG"] == "FETCH_FAILED"
    assert summary["is_complete"] is True


def test_to_dict_preserves_symbol_lists():
    report = _make_report(cn_symbols=["SH600000", "SZ000001"])
    report.add("updated", "cn", "SH600000")
    report.add("reused", "cn", "SZ000001")

    payload = report.to_dict()

    assert payload["configured"]["cn"] == ["SH600000", "SZ000001"]
    assert "SH600000" in payload["updated"]["cn"]
    assert "SZ000001" in payload["reused"]["cn"]
    assert payload["is_complete"] is True


def test_add_normalizes_market_and_symbol_and_rejects_invalid_state():
    report = _make_report(us_symbols=["aapl"])
    report.add("updated", "US", "aapl")
    assert "AAPL" in report.updated["us"]

    with pytest.raises(ValueError, match="unsupported accounting state"):
        report.add("configured", "us", "AAPL")


def test_market_summary_returns_per_state_counts():
    report = _make_report(cn_symbols=["A", "B", "C"])
    report.add("updated", "cn", "A")
    report.add("failed", "cn", "B")
    report.add("excluded", "cn", "C")

    summary = report.market_summary("cn")

    assert summary["configured"] == 3
    assert summary["updated"] == 1
    assert summary["failed"] == 1
    assert summary["excluded"] == 1
    assert summary["reused"] == 0


def test_factory_returns_incomplete_configured_report():
    report = create_accounting_report(configured={"us": ["AAPL", "GOOG"]})
    assert isinstance(report, UpdateAccountingReport)
    assert report.configured["us"] == ["AAPL", "GOOG"]
    assert report.is_complete is False


def test_publish_validation_accepts_complete_update():
    report = _make_report(us_symbols=["AAPL", "GOOG"])
    for symbol in report.configured["us"]:
        report.add("attempted", "us", symbol)
        report.add("updated", "us", symbol)
    report.validate_for_publish(selected_markets={"us"})


def test_publish_validation_rejects_zero_or_partial_updates():
    zero_update = _make_report(us_symbols=["AAPL"])
    zero_update.add("attempted", "us", "AAPL")
    zero_update.add("updated", "us", "AAPL")
    zero_update.updated["us"] = set()
    with pytest.raises(DataUpdateFailure, match="partial update"):
        zero_update.validate_for_publish(selected_markets={"us"})

    partial = _make_report(us_symbols=["AAPL", "GOOG"])
    partial.add("attempted", "us", "AAPL")
    partial.add("attempted", "us", "GOOG")
    partial.add("updated", "us", "AAPL")
    partial.add("failed", "us", "GOOG", reason=FailureReason.FETCH_FAILED)
    with pytest.raises(DataUpdateFailure, match="partial update"):
        partial.validate_for_publish(selected_markets={"us"})


def test_data_update_failure_is_runtime_error():
    with pytest.raises(RuntimeError):
        raise DataUpdateFailure("test failure")
