from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    FetchResult,
    ProviderContractError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from src.data.etf_reference_bundle import build_etf_reference_bundle
from src.data.provider_retry import RetryPolicy, call_with_retry, classify_transient

CONTRACT = Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml")


def _bars(symbol: str, *, start: str = "2024-01-29", periods: int = 25) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    base = {"QQQ": 400.0, "QQQI": 50.0, "TQQQ": 60.0}[symbol]
    close = pd.Series(base * np.cumprod(np.full(periods, 1.001)), index=dates)
    open_price = close * 0.999
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_price.values,
            "high": (close * 1.01).values,
            "low": (open_price * 0.99).values,
            "close": close.values,
            "volume": np.arange(periods, dtype=float) + 1000.0,
            "amount": close.values * (np.arange(periods, dtype=float) + 1000.0),
            "factor": np.ones(periods),
        }
    )


FRAMES = {symbol: _bars(symbol) for symbol in ("QQQ", "QQQI", "TQQQ")}


@dataclass
class FakeAdapter:
    _name: str = "tiingo"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        frame = FRAMES[req.symbol.upper()].copy()
        frame.attrs["provider_metadata"] = {"ticker": req.symbol.upper()}
        return FetchResult(
            provider=self.name,
            symbol=req.symbol.upper(),
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=req.symbol.upper(),
        )


@dataclass
class FlakyAdapter:
    failures: int
    error: Exception
    _name: str = "tiingo"
    calls: int = 0
    calls_by_symbol: dict[str, int] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls += 1
        symbol = req.symbol.upper()
        self.calls_by_symbol[symbol] = self.calls_by_symbol.get(symbol, 0) + 1
        if self.calls_by_symbol[symbol] <= self.failures:
            raise self.error
        frame = FRAMES[symbol].copy()
        return FetchResult(
            provider=self.name,
            symbol=req.symbol.upper(),
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=req.symbol.upper(),
        )


NO_DELAY = RetryPolicy(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0, jitter_ratio=0.0)


def test_classify_transient_only_retries_transport_shapes() -> None:
    assert classify_transient(ProviderTimeoutError("timeout")) == (True, None)
    assert classify_transient(ProviderRateLimitError("slow", retry_after_seconds=5.0)) == (
        True,
        5.0,
    )
    assert classify_transient(DataFetchError("schema nonsense")) == (False, None)
    assert classify_transient(ProviderContractError("identity mismatch")) == (False, None)


def test_classify_transient_uses_http_status_not_urlerror_umbrella() -> None:
    rate_limited = urllib.error.HTTPError(
        url="https://example.invalid",
        code=429,
        msg="too many",
        hdrs={"Retry-After": "7"},
        fp=None,
    )
    unavailable = urllib.error.HTTPError(
        url="https://example.invalid", code=503, msg="bad gateway", hdrs={}, fp=None
    )
    missing = urllib.error.HTTPError(
        url="https://example.invalid", code=404, msg="not found", hdrs={}, fp=None
    )
    assert classify_transient(rate_limited) == (True, 7.0)
    assert classify_transient(unavailable) == (True, None)
    assert classify_transient(missing) == (False, None)


def test_transient_then_success_retries_and_records_attempts() -> None:
    calls = 0
    sleeps: list[float] = []
    evidence: dict[str, object] = {}

    def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderTimeoutError("timed out")
        return "ok"

    outcome = call_with_retry(
        flaky,
        policy=RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.5,
            max_delay_seconds=8.0,
            jitter_ratio=0.0,
        ),
        sleep=sleeps.append,
        evidence=evidence,
    )

    assert outcome.value == "ok"
    assert outcome.attempts == 3
    assert outcome.outcome == "succeeded_after_retry"
    assert sleeps == [0.5, 1.0]
    assert evidence["retry_attempts"] == 3
    assert evidence["retry_outcome"] == "succeeded_after_retry"
    assert [item["attempt"] for item in evidence["retry_history"]] == [1, 2]


def test_exhausted_transients_fail_closed_after_the_bound() -> None:
    calls = 0
    evidence: dict[str, object] = {}

    def always_transient():
        nonlocal calls
        calls += 1
        raise ProviderTimeoutError("still down")

    with pytest.raises(ProviderTimeoutError):
        call_with_retry(always_transient, policy=NO_DELAY, sleep=lambda _: None, evidence=evidence)

    assert calls == 3
    assert evidence["retry_attempts"] == 3
    assert evidence["retry_outcome"] == "exhausted"
    assert evidence["retry_history"][-1]["stop_reason"] == "attempts_exhausted"


def test_non_transient_failure_is_not_retried() -> None:
    calls = 0
    evidence: dict[str, object] = {}

    def contract_failure():
        nonlocal calls
        calls += 1
        raise ProviderContractError("schema/identity defect")

    with pytest.raises(ProviderContractError):
        call_with_retry(contract_failure, policy=NO_DELAY, sleep=lambda _: None, evidence=evidence)

    assert calls == 1
    assert evidence["retry_attempts"] == 1
    assert evidence["retry_outcome"] == "not_retried"
    assert evidence["retry_history"][0]["stop_reason"] == "non_transient"


def test_retry_after_beyond_the_bound_is_not_slept_on() -> None:
    calls = 0
    sleeps: list[float] = []
    evidence: dict[str, object] = {}

    def rate_limited():
        nonlocal calls
        calls += 1
        raise ProviderRateLimitError("hourly quota", retry_after_seconds=3600.0)

    with pytest.raises(ProviderRateLimitError):
        call_with_retry(
            rate_limited,
            policy=RetryPolicy(max_attempts=3, max_honored_retry_after_seconds=30.0),
            sleep=sleeps.append,
            evidence=evidence,
        )

    assert calls == 1
    assert sleeps == []
    assert evidence["retry_outcome"] == "not_retried"
    assert evidence["retry_history"][0]["stop_reason"] == "retry_after_exceeds_bound"


def test_bundle_records_retry_provenance_for_transient_then_success(tmp_path: Path) -> None:
    primary = FlakyAdapter(failures=1, error=ProviderTimeoutError("one blip"))
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=primary,
        fallback_adapter=FakeAdapter("yfinance"),
        retry_policy=NO_DELAY,
    )

    assert primary.calls == 6  # one transient retry per symbol
    assert manifest["provider_order"] == ["tiingo", "yfinance"]
    coverage = pd.read_csv(tmp_path / "coverage.csv")
    attempts = coverage["primary_attempt"].map(json.loads)
    assert {attempt["retry_outcome"] for attempt in attempts} == {"succeeded_after_retry"}
    assert {attempt["retry_attempts"] for attempt in attempts} == {2}
    assert {attempt["ok"] for attempt in attempts} == {True}


def test_bundle_fails_closed_when_transients_are_exhausted(tmp_path: Path) -> None:
    primary = FlakyAdapter(failures=999, error=ProviderTimeoutError("provider down"))
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=primary,
        fallback_adapter=FakeAdapter("yfinance"),
        retry_policy=NO_DELAY,
    )

    assert primary.calls == 9  # three attempts for each of three symbols
    assert manifest["selected_providers"] == {
        "QQQ": "yfinance",
        "QQQI": "yfinance",
        "TQQQ": "yfinance",
    }
    assert manifest["professional_source_ready"] is False
    coverage = pd.read_csv(tmp_path / "coverage.csv")
    attempts = coverage["primary_attempt"].map(json.loads)
    assert {attempt["retry_outcome"] for attempt in attempts} == {"exhausted"}
    assert {attempt["ok"] for attempt in attempts} == {False}


def test_bundle_does_not_retry_non_transient_failure(tmp_path: Path) -> None:
    primary = FlakyAdapter(failures=999, error=ProviderContractError("bad schema"))
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=primary,
        fallback_adapter=FakeAdapter("yfinance"),
        retry_policy=NO_DELAY,
    )

    assert primary.calls == 3  # one attempt per symbol, no retry
    coverage = pd.read_csv(tmp_path / "coverage.csv")
    attempts = coverage["primary_attempt"].map(json.loads)
    assert {attempt["retry_outcome"] for attempt in attempts} == {"not_retried"}
    assert {attempt["error_class"] for attempt in attempts} == {"provider_contract_error"}
    assert manifest["strategy_data_ready"] is True
    assert manifest["professional_source_ready"] is False
