"""Tests for the update_data resume ledger and router circuit breaker."""

from __future__ import annotations

from pathlib import Path

from scripts.update_data import _ResumeLedger, _router_failure_threshold


def _ledger(tmp_path: Path, **overrides) -> _ResumeLedger:
    kwargs = {
        "path": tmp_path / "resume_all.json",
        "market": "all",
        "full": False,
        "start": "2020-01-01",
        "end": None,
        "lookback_days": 30,
    }
    kwargs.update(overrides)
    return _ResumeLedger(**kwargs)


def test_resume_ledger_roundtrip_skips_unchanged_csv(tmp_path: Path):
    csv_path = tmp_path / "AAA.csv"
    csv_path.write_text("date,close\n2026-01-02,1\n", encoding="utf-8")

    ledger = _ledger(tmp_path)
    assert ledger.should_skip("AAA", csv_path) is False
    ledger.mark_completed("AAA", csv_path)

    reloaded = _ledger(tmp_path)
    assert reloaded.should_skip("aaa", csv_path) is True

    csv_path.write_text("date,close\n2026-01-02,2\n2026-01-03,3\n", encoding="utf-8")
    assert reloaded.should_skip("AAA", csv_path) is False


def test_resume_ledger_identity_mismatch_is_ignored(tmp_path: Path):
    csv_path = tmp_path / "AAA.csv"
    csv_path.write_text("date,close\n2026-01-02,1\n", encoding="utf-8")

    ledger = _ledger(tmp_path)
    ledger.mark_completed("AAA", csv_path)

    other_interval = _ledger(tmp_path, end="2026-01-03")
    assert other_interval.should_skip("AAA", csv_path) is False


def test_resume_ledger_finish_only_removes_when_clean(tmp_path: Path):
    csv_path = tmp_path / "AAA.csv"
    csv_path.write_text("date,close\n2026-01-02,1\n", encoding="utf-8")

    ledger = _ledger(tmp_path)
    ledger.mark_completed("AAA", csv_path)
    ledger.finish()
    assert not ledger.path.exists()

    ledger.mark_failed("AAA")
    assert ledger.path.exists()
    ledger.finish()
    assert ledger.path.exists()


def test_router_failure_threshold_env(monkeypatch):
    monkeypatch.setenv("ALPHA_ENGINE_ROUTER_FAILURE_THRESHOLD", "3")
    assert _router_failure_threshold() == 3

    monkeypatch.setenv("ALPHA_ENGINE_ROUTER_FAILURE_THRESHOLD", "0")
    assert _router_failure_threshold() is None

    monkeypatch.delenv("ALPHA_ENGINE_ROUTER_FAILURE_THRESHOLD")
    assert _router_failure_threshold() == 5
