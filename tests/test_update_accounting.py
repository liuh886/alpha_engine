"""Tests for src.data.update_accounting -- truthful data update outcomes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.update_accounting import (
    DataUpdateFailure,
    FailureReason,
    UpdateAccountingReport,
    create_accounting_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(
    *,
    cn_symbols: list[str] | None = None,
    us_symbols: list[str] | None = None,
) -> UpdateAccountingReport:
    """Create a report with typical CN/US configured symbols."""
    configured: dict[str, list[str]] = {}
    if cn_symbols is not None:
        configured["cn"] = cn_symbols
    if us_symbols is not None:
        configured["us"] = us_symbols
    return UpdateAccountingReport(configured=configured)


# ---------------------------------------------------------------------------
# Test 1: complete accounting report is_complete
# ---------------------------------------------------------------------------


def test_complete_report_is_complete():
    """All configured symbols accounted for => is_complete is True."""
    report = _make_report(cn_symbols=["SH600000", "SZ000001"], us_symbols=["AAPL", "MSFT"])

    # Mark all symbols as updated
    report.add("updated", "cn", "SH600000")
    report.add("updated", "cn", "SZ000001")
    report.add("updated", "us", "AAPL")
    report.add("updated", "us", "MSFT")

    assert report.is_complete is True


def test_complete_report_with_mixed_terminal_states():
    """Mix of updated, reused, excluded, failed, stale still counts as complete."""
    report = _make_report(cn_symbols=["SH600000", "SZ000001", "SZ000002", "SZ000003", "SZ000004"])

    report.add("updated", "cn", "SH600000")
    report.add("reused", "cn", "SZ000001")
    report.add("excluded", "cn", "SZ000002", reason=FailureReason.EXCLUDED_BY_POLICY)
    report.add("failed", "cn", "SZ000003", reason=FailureReason.FETCH_FAILED)
    report.add("stale", "cn", "SZ000004", reason=FailureReason.STALE_DATA)

    assert report.is_complete is True


# ---------------------------------------------------------------------------
# Test 2: missing symbols make the report NOT complete
# ---------------------------------------------------------------------------


def test_missing_symbols_not_complete():
    """If a configured symbol has no terminal state, is_complete is False."""
    report = _make_report(cn_symbols=["SH600000", "SZ000001"])

    # Only mark one symbol
    report.add("updated", "cn", "SH600000")

    assert report.is_complete is False


def test_empty_attempted_not_complete():
    """Symbols that were configured but never attempted are not complete."""
    report = _make_report(us_symbols=["AAPL", "GOOG"])

    # Attempted + updated only AAPL, GOOG was never even attempted
    report.add("attempted", "us", "AAPL")
    report.add("updated", "us", "AAPL")

    assert report.is_complete is False


def test_empty_report_not_complete():
    """A report with configured symbols but no activity is not complete."""
    report = _make_report(cn_symbols=["SH600000"])
    assert report.is_complete is False


def test_no_configured_symbols_is_complete():
    """A report with zero configured symbols vacuously has everything accounted for."""
    report = UpdateAccountingReport(configured={})
    assert report.is_complete is True


# ---------------------------------------------------------------------------
# Test 3: each failure reason is a valid typed enum
# ---------------------------------------------------------------------------


def test_failure_reason_enum_members():
    """All expected failure reasons exist as enum members."""
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
    actual = {member.name for member in FailureReason}
    assert expected == actual


def test_failure_reason_str_values():
    """Enum values match their names (str mixin)."""
    for member in FailureReason:
        assert member.value == member.name


@pytest.mark.parametrize("reason", list(FailureReason))
def test_failure_reason_can_be_used_as_add_reason(reason: FailureReason):
    """Every FailureReason value can be passed to add() and stored."""
    report = _make_report(us_symbols=["AAPL"])
    report.add("failed", "us", "AAPL", reason=reason)
    assert report.reasons["failed"]["us:AAPL"] == reason.value


# ---------------------------------------------------------------------------
# Test 4: summary_dict includes all required fields
# ---------------------------------------------------------------------------


def test_summary_dict_has_required_fields():
    """summary_dict() returns all fields expected by the API/dashboard."""
    report = _make_report(cn_symbols=["SH600000"], us_symbols=["AAPL"])
    report.add("updated", "cn", "SH600000")
    report.add("updated", "us", "AAPL")

    summary = report.summary_dict()

    # Top-level keys
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
        assert key in summary, f"missing key: {key}"

    # Per-market keys
    for market in ("cn", "us"):
        assert market in summary["markets"]
        market_data = summary["markets"][market]
        for field in (
            "configured",
            "attempted",
            "updated",
            "reused",
            "excluded",
            "failed",
            "stale",
        ):
            assert field in market_data, f"missing field {field} in market {market}"


def test_summary_dict_counts_are_correct():
    """summary_dict() returns correct symbol counts."""
    report = _make_report(cn_symbols=["A", "B", "C"])
    report.add("updated", "cn", "A")
    report.add("failed", "cn", "B", reason=FailureReason.FETCH_FAILED)
    report.add("stale", "cn", "C", reason=FailureReason.STALE_DATA)

    summary = report.summary_dict()

    assert summary["total_configured"] == 3
    assert summary["total_updated"] == 1
    assert summary["total_failed"] == 1
    assert summary["total_stale"] == 1
    assert summary["is_complete"] is True


def test_summary_dict_with_reasons():
    """summary_dict() includes failure reasons."""
    report = _make_report(us_symbols=["AAPL", "GOOG"])
    report.add("failed", "us", "AAPL", reason=FailureReason.FETCH_FAILED)
    report.add("failed", "us", "GOOG", reason=FailureReason.VALIDATION_FAILED)

    summary = report.summary_dict()

    assert summary["reasons"]["failed"]["us:AAPL"] == "FETCH_FAILED"
    assert summary["reasons"]["failed"]["us:GOOG"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Test 5: to_dict preserves full symbol lists
# ---------------------------------------------------------------------------


def test_to_dict_preserves_symbol_lists():
    """to_dict() returns symbol lists, not just counts."""
    report = _make_report(cn_symbols=["SH600000", "SZ000001"])
    report.add("updated", "cn", "SH600000")
    report.add("reused", "cn", "SZ000001")

    d = report.to_dict()

    assert d["configured"]["cn"] == ["SH600000", "SZ000001"]
    assert "SH600000" in d["updated"]["cn"]
    assert "SZ000001" in d["reused"]["cn"]
    assert d["is_complete"] is True


# ---------------------------------------------------------------------------
# Test 6: add() normalises market and symbol
# ---------------------------------------------------------------------------


def test_add_normalises_market_and_symbol():
    """Market is lowercased, symbol is uppercased."""
    report = _make_report(us_symbols=["aapl"])
    report.add("updated", "US", "aapl")

    assert "AAPL" in report.updated["us"]


def test_add_rejects_invalid_state():
    """add() raises ValueError for the 'configured' state."""
    report = _make_report(us_symbols=["AAPL"])
    with pytest.raises(ValueError, match="unsupported accounting state"):
        report.add("configured", "us", "AAPL")


# ---------------------------------------------------------------------------
# Test 7: market_summary
# ---------------------------------------------------------------------------


def test_market_summary():
    """market_summary returns per-state counts for a single market."""
    report = _make_report(cn_symbols=["A", "B", "C"])
    report.add("updated", "cn", "A")
    report.add("failed", "cn", "B")
    report.add("excluded", "cn", "C")

    ms = report.market_summary("cn")

    assert ms["configured"] == 3
    assert ms["updated"] == 1
    assert ms["failed"] == 1
    assert ms["excluded"] == 1
    assert ms["reused"] == 0


# ---------------------------------------------------------------------------
# Test 8: create_accounting_report factory
# ---------------------------------------------------------------------------


def test_create_accounting_report_factory():
    """Factory function creates a valid report."""
    report = create_accounting_report(configured={"us": ["AAPL", "GOOG"]})
    assert isinstance(report, UpdateAccountingReport)
    assert report.configured["us"] == ["AAPL", "GOOG"]
    assert report.is_complete is False


# ---------------------------------------------------------------------------
# Test 9: validate_for_publish gates unconditional success
# ---------------------------------------------------------------------------


def test_validate_for_publish_passes_when_complete():
    """validate_for_publish succeeds when all symbols are updated."""
    report = _make_report(us_symbols=["AAPL", "GOOG"])
    report.add("attempted", "us", "AAPL")
    report.add("attempted", "us", "GOOG")
    report.add("updated", "us", "AAPL")
    report.add("updated", "us", "GOOG")

    # Should not raise
    report.validate_for_publish(selected_markets={"us"})


def test_validate_for_publish_fails_on_zero_updates():
    """validate_for_publish raises when zero symbols were updated."""
    report = _make_report(us_symbols=["AAPL"])
    report.add("attempted", "us", "AAPL")
    report.add("updated", "us", "AAPL")

    # Replace the updated set to simulate zero updates
    report.updated["us"] = set()

    with pytest.raises(DataUpdateFailure, match="partial update"):
        report.validate_for_publish(selected_markets={"us"})


def test_validate_for_publish_fails_on_partial_failure():
    """validate_for_publish raises when some symbols failed."""
    report = _make_report(us_symbols=["AAPL", "GOOG"])
    report.add("attempted", "us", "AAPL")
    report.add("attempted", "us", "GOOG")
    report.add("updated", "us", "AAPL")
    report.add("failed", "us", "GOOG", reason=FailureReason.FETCH_FAILED)

    with pytest.raises(DataUpdateFailure, match="partial update"):
        report.validate_for_publish(selected_markets={"us"})


# ---------------------------------------------------------------------------
# Test 10: DataUpdateFailure is a RuntimeError subclass
# ---------------------------------------------------------------------------


def test_data_update_failure_is_runtime_error():
    """DataUpdateFailure can be caught as RuntimeError."""
    with pytest.raises(RuntimeError):
        raise DataUpdateFailure("test failure")


# ---------------------------------------------------------------------------
# Test 11: Health liveness endpoint always returns 200
# ---------------------------------------------------------------------------


def test_health_live_always_returns_200(monkeypatch: pytest.MonkeyPatch):
    """The /api/health/live endpoint always returns 200 if the process is up."""
    # Ensure auth env vars are set so the app can start
    monkeypatch.setenv("TRADING_UI_USER", "agent")
    monkeypatch.setenv("TRADING_UI_PASSWORD", "alpha2026")

    from fastapi.testclient import TestClient

    from api_server import app

    with TestClient(app) as client:
        resp = client.get("/api/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"
    assert "version" in body


# ---------------------------------------------------------------------------
# Test 12: Health readiness endpoint returns 503 when snapshot is missing
# ---------------------------------------------------------------------------


def test_health_ready_returns_503_when_snapshot_missing(monkeypatch: pytest.MonkeyPatch):
    """The /api/health/ready endpoint returns 503 when no snapshot exists."""
    monkeypatch.setenv("TRADING_UI_USER", "agent")
    monkeypatch.setenv("TRADING_UI_PASSWORD", "alpha2026")

    # Patch DataSnapshot.get_latest_snapshot to return None
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from api_server import app

    with patch("src.data.snapshot.DataSnapshot.get_latest_snapshot", return_value=None):
        with TestClient(app) as client:
            resp = client.get("/api/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert "checks" in body
    assert body["checks"]["snapshot"]["status"] == "unavailable"


def test_health_ready_returns_200_when_all_ok(monkeypatch: pytest.MonkeyPatch):
    """The /api/health/ready endpoint returns 200 when all checks pass."""
    monkeypatch.setenv("TRADING_UI_USER", "agent")
    monkeypatch.setenv("TRADING_UI_PASSWORD", "alpha2026")

    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from api_server import app

    # Mock a valid snapshot
    mock_snapshot = MagicMock()
    mock_snapshot.snapshot_id = "test_snap_123"
    mock_snapshot.manifest.quality_verdict = "pass"

    # Mock model registry index
    mock_index = MagicMock()
    mock_index.list_versions.return_value = [{"id": "model_1"}]

    with (
        patch("src.data.snapshot.DataSnapshot.get_latest_snapshot", return_value=mock_snapshot),
        patch("src.assistant.model_registry_index.ModelRegistryIndex", return_value=mock_index),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["snapshot"]["status"] == "ok"
    assert body["checks"]["model_registry"]["status"] == "ok"
