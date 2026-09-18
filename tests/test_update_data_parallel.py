"""Tests for parallel provider downloads in update_data."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from scripts.update_data import (
    _ResumeLedger,
    _download_symbol,
    _resolve_fetch_start,
    _resolve_update_workers,
)


class _FakeRouter:
    def __init__(self, *, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def fetch_daily_bars(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider exploded")
        return SimpleNamespace(
            ok=True,
            result=SimpleNamespace(df=pd.DataFrame()),
            attempts=[],
        )


def _args(**overrides) -> SimpleNamespace:
    values = {
        "start": "2020-01-01",
        "end": None,
        "full": False,
        "lookback_days": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_resolve_update_workers_env(monkeypatch):
    monkeypatch.delenv("ALPHA_ENGINE_UPDATE_WORKERS", raising=False)
    assert _resolve_update_workers(10) == 4
    assert _resolve_update_workers(3) == 3

    monkeypatch.setenv("ALPHA_ENGINE_UPDATE_WORKERS", "1")
    assert _resolve_update_workers(10) == 1

    monkeypatch.setenv("ALPHA_ENGINE_UPDATE_WORKERS", "8")
    assert _resolve_update_workers(3) == 3

    monkeypatch.setenv("ALPHA_ENGINE_UPDATE_WORKERS", "0")
    assert _resolve_update_workers(10) == 1

    monkeypatch.setenv("ALPHA_ENGINE_UPDATE_WORKERS", "not-a-number")
    assert _resolve_update_workers(10) == 4


def test_resolve_fetch_start_uses_lookback():
    existing = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-01", "2026-01-31"]), "close": [1.0, 2.0]}
    )
    assert _resolve_fetch_start(existing, _args(lookback_days=30)) == "2026-01-01"
    assert _resolve_fetch_start(None, _args()) == "2020-01-01"


def test_download_symbol_returns_fetched_payload(tmp_path: Path):
    router = _FakeRouter()
    payload = _download_symbol(
        "us",
        "aapl",
        args=_args(),
        router=router,
        source_dir=tmp_path,
        resume_ledger=None,
    )

    assert payload["status"] == "fetched"
    assert payload["start"] == "2020-01-01"
    assert payload["existing"] is None
    assert router.calls == [
        {
            "symbol": "AAPL",
            "market": "us",
            "start": "2020-01-01",
            "end": None,
            "validate": True,
        }
    ]


def test_download_symbol_marks_router_error(tmp_path: Path):
    payload = _download_symbol(
        "us",
        "AAPL",
        args=_args(),
        router=_FakeRouter(fail=True),
        source_dir=tmp_path,
        resume_ledger=None,
    )

    assert payload["status"] == "error"
    assert "provider exploded" in payload["error"]


def test_download_symbol_resumes_completed_symbol(tmp_path: Path):
    csv_path = tmp_path / "AAPL.csv"
    csv_path.write_text("date,close\n2026-01-02,1.0\n", encoding="utf-8")

    ledger = _ResumeLedger(
        path=tmp_path / "resume_us.json",
        market="us",
        full=False,
        start="2020-01-01",
        end=None,
        lookback_days=30,
    )
    ledger.mark_completed("AAPL", csv_path)

    router = _FakeRouter()
    payload = _download_symbol(
        "us",
        "AAPL",
        args=_args(),
        router=router,
        source_dir=tmp_path,
        resume_ledger=ledger,
    )

    assert payload == {"status": "resumed"}
    assert router.calls == []
